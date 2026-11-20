"""Fetch Kalshi's public game markets (winner, spread, total, team totals) for NFL, CFB, NBA, NHL, men's CBB and UFC fights
and write kalshi.json for the Line Shop page, plus NBA player props (points, rebounds, assists, threes and combos)
to kalshi-props.json for the Prop Shop page. Read-only public market data; no account, no orders.
Run by .github/workflows/kalshi.yml every 10 minutes."""
import json, re, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BASE = 'https://external-api.kalshi.com/trade-api/v2'
LEAGUES = {'nfl': 'KXNFL', 'ncaaf': 'KXNCAAF', 'nba': 'KXNBA', 'nhl': 'KXNHL', 'ncaab': 'KXNCAAMB'}
KINDS = {'GAME': 'game', 'SPREAD': 'spread', 'TOTAL': 'total', 'TEAMTOTAL': 'teamtotal'}
HORIZON = timedelta(days=5)
# UFC fights: one winner market per fighter (no spread/total series), same shape as a game's winner market
EXTRA_GAME_SERIES = {'ufc': 'KXUFCFIGHT'}
# UFC method markets: method of victory (fighter by KO/TKO/DQ, submission, decision), method of finish (fight ends by ...), goes the distance
UFC_METHOD_SERIES = {'KXUFCMOV': 'mov', 'KXUFCMOF': 'mof', 'KXUFCDISTANCE': 'dist'}
UFC_KIND = {'KOTKODQ': 'KO', 'SUB': 'SUB', 'DEC': 'DEC'}

def fight_names(title):
    # "Fight Night: A vs B", "A vs B: Method of Victory", "A vs. B: Go the Distance" -> [A, B]
    t = title or ''
    if re.match(r'^(fight night|ufc[^:]*):', t, re.I): t = t.split(':', 1)[1]
    t = t.split(':', 1)[0].strip()
    parts = re.split(r'\s+vs\.?\s+', t, flags=re.I)
    return [x.strip() for x in parts] if len(parts) == 2 else []

def ufc_key(event_ticker, title):
    # one entry per fight for all UFC series: card date + both fighters' last names
    names = fight_names(title)
    date = event_ticker.split('-', 1)[1][:7]
    if not names: return None
    return 'ufc:' + date + ':' + '|'.join(sorted(n.split()[-1].lower() for n in names))

def get(path, params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'line-shop/1.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 3: raise
            time.sleep(2 + 3 * attempt)

def f(x):
    try: return round(float(x), 4)
    except (TypeError, ValueError): return None

# NBA player props: each market is "Player: N+ <stat>" (yes = over N-0.5)
NBA_PROP_SERIES = {'KXNBAPTS': 'pts', 'KXNBAREB': 'reb', 'KXNBAAST': 'ast', 'KXNBA3PT': '3pm',
                   'KXNBAPR': 'pr', 'KXNBAPA': 'pa', 'KXNBARA': 'ra', 'KXNBAPRA': 'pra'}

def prop_player_line(m):
    # player name and threshold from the market; Kalshi writes e.g. "LeBron James: 25+ points" / yes_sub_title "LeBron James: 25+"
    texts = [m.get('yes_sub_title') or '', m.get('title') or '', m.get('subtitle') or '']
    name, n = None, None
    for t in texts:
        mt = re.match(r'^\s*(.+?)\s*[:\-\u2013]\s*(\d+(?:\.\d+)?)\s*\+', t)
        if mt: name, n = mt.group(1).strip(), float(mt.group(2)); break
        mt = re.match(r'^\s*(?:will\s+)?(.+?)\s+(?:record|score|have|get)?\s*(?:at least|over)\s+(\d+(?:\.\d+)?)', t, re.I)
        if mt: name, n = mt.group(1).strip(), float(mt.group(2)) + (0 if 'at least' in t.lower() else 0.5); break
    if n is not None:
        line = n - 0.5 if n % 1 == 0 else n
    elif m.get('floor_strike') is not None:
        fs = float(m['floor_strike'])
        # "greater" than 24.5 or 25 -> over 24.5 / 25.5; "greater_or_equal" 25 -> over 24.5
        line = fs if fs % 1 else (fs + 0.5 if m.get('strike_type') == 'greater' else fs - 0.5)
    else:
        line = None
    return name, line

def fetch_props(now, out):
    props, errors = [], []
    for series, stat in NBA_PROP_SERIES.items():
        cursor = None
        try:
            while True:
                p = {'series_ticker': series, 'status': 'open', 'limit': 200, 'with_nested_markets': 'true'}
                if cursor: p['cursor'] = cursor
                d = get('/events', p)
                for ev in d.get('events', []):
                    suffix = ev['event_ticker'].split('-', 1)[1]
                    for m in ev.get('markets', []):
                        exp = m.get('expected_expiration_time') or m.get('close_time')
                        try: t = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                        except Exception: continue
                        if t < now or t > now + HORIZON: continue
                        name, line = prop_player_line(m)
                        if not name or line is None: continue
                        props.append({'game': suffix, 'title': ev.get('title'), 'stat': stat, 'player': name, 'line': line,
                                      'ya': f(m.get('yes_ask_dollars')), 'na': f(m.get('no_ask_dollars')),
                                      'vol': f(m.get('volume_fp')), 'ticker': m.get('ticker'), 'exp': exp})
                cursor = d.get('cursor')
                if not cursor: break
        except Exception as e:
            errors.append(f'{series}: {e}')
    data = {'updated': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'errors': errors, 'props': props}
    with open(out, 'w') as fh: json.dump(data, fh, separators=(',', ':'))
    print(len(props), 'NBA props;', len(errors), 'errors', errors[:3])

def main(out, props_out=None):
    now = datetime.now(timezone.utc)
    games, errors = {}, []
    jobs = [(league, prefix + kind, key) for league, prefix in LEAGUES.items() for kind, key in KINDS.items()]
    jobs += [(league, series, 'game') for league, series in EXTRA_GAME_SERIES.items()]
    jobs += [('ufc', series, key) for series, key in UFC_METHOD_SERIES.items()]
    for league, series, key in jobs:
            cursor = None
            try:
                while True:
                    p = {'series_ticker': series, 'status': 'open', 'limit': 200, 'with_nested_markets': 'true'}
                    if cursor: p['cursor'] = cursor
                    d = get('/events', p)
                    for ev in d.get('events', []):
                        suffix = ev['event_ticker'].split('-', 1)[1]
                        gkey = league + ':' + suffix
                        if league == 'ufc':
                            gkey = ufc_key(ev['event_ticker'], ev.get('title')) or gkey
                        for m in ev.get('markets', []):
                            exp = m.get('expected_expiration_time') or m.get('close_time')
                            try: t = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                            except Exception: continue
                            if t < now or t > now + HORIZON: continue
                            g = games.setdefault(gkey, {'league': league, 'key': suffix, 'title': ev.get('title'),
                                                        'sub': ev.get('sub_title'), 'exp': exp, 'teams': {}, 'game': [], 'spread': [], 'total': [], 'teamtotal': []})
                            if league == 'ufc' and not g['teams']:
                                for n in fight_names(ev.get('title')): g['teams'][n.split()[-1].upper()[:3]] = n
                            row = {'ya': f(m.get('yes_ask_dollars')), 'na': f(m.get('no_ask_dollars')), 'vol': f(m.get('volume_fp'))}
                            code = m['ticker'].rsplit('-', 1)[1]
                            if key == 'game':
                                row.update(team=m.get('yes_sub_title'), code=code)
                                g['teams'][code] = m.get('yes_sub_title')
                            elif key == 'mov':
                                kind = UFC_KIND.get(re.sub(r'^[A-Z]{3}', '', code)) if code != 'DRAW' else None
                                if not kind: continue
                                row.update(team=re.sub(r'\s+by\s+.*$', '', m.get('yes_sub_title') or ''), code=code[:3], kind=kind)
                                g.setdefault('mov', []).append(row); continue
                            elif key == 'mof':
                                kind = UFC_KIND.get(code)
                                if not kind: continue
                                row.update(kind=kind); g.setdefault('mof', []).append(row); continue
                            elif key == 'dist':
                                g['dist'] = row; continue
                            elif key == 'spread':
                                mt = re.match(r'^(.*?) wins by over ([\d.]+)', m.get('title') or m.get('yes_sub_title') or '')
                                if not mt: continue
                                row.update(team=mt.group(1).strip(), code=re.sub(r'\d+$', '', code), strike=float(mt.group(2)))
                            elif key == 'teamtotal':
                                mt = re.match(r'^(.*?) over ([\d.]+) points', m.get('title') or m.get('yes_sub_title') or '')
                                if not mt: continue
                                row.update(team=mt.group(1).strip(), code=re.sub(r'\d+$', '', code), strike=float(mt.group(2)))
                            else:
                                if m.get('floor_strike') is None: continue
                                row.update(strike=float(m['floor_strike']))
                            g[key].append(row)
                    cursor = d.get('cursor')
                    if not cursor: break
            except Exception as e:
                errors.append(f'{series}: {e}')
    data = {'updated': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'errors': errors, 'games': list(games.values())}
    with open(out, 'w') as fh: json.dump(data, fh, separators=(',', ':'))
    print(len(games), 'games;', len(errors), 'errors', errors[:3])
    if props_out:
        # props never fail the job: a problem there must not stop the Line Shop's kalshi.json from publishing
        try: fetch_props(now, props_out)
        except Exception as e: print('props failed:', e)
    if errors and not games: sys.exit(1)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'kalshi.json', sys.argv[2] if len(sys.argv) > 2 else None)
