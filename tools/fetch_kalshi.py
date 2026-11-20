"""Fetch Kalshi's public game markets (winner, spread, total) for NFL, CFB, NBA, NHL and men's CBB
and write kalshi.json for the Line Shop page. Read-only public market data; no account, no orders.
Run by .github/workflows/kalshi.yml every 10 minutes."""
import json, re, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BASE = 'https://external-api.kalshi.com/trade-api/v2'
LEAGUES = {'nfl': 'KXNFL', 'ncaaf': 'KXNCAAF', 'nba': 'KXNBA', 'nhl': 'KXNHL', 'ncaab': 'KXNCAAMB'}
KINDS = {'GAME': 'game', 'SPREAD': 'spread', 'TOTAL': 'total'}
HORIZON = timedelta(days=5)

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

def main(out):
    now = datetime.now(timezone.utc)
    games, errors = {}, []
    for league, prefix in LEAGUES.items():
        for kind, key in KINDS.items():
            series, cursor = prefix + kind, None
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
                            g = games.setdefault(league + ':' + suffix, {'league': league, 'key': suffix, 'title': ev.get('title'),
                                                                        'sub': ev.get('sub_title'), 'exp': exp, 'teams': {}, 'game': [], 'spread': [], 'total': []})
                            row = {'ya': f(m.get('yes_ask_dollars')), 'na': f(m.get('no_ask_dollars')), 'vol': f(m.get('volume_fp'))}
                            code = m['ticker'].rsplit('-', 1)[1]
                            if key == 'game':
                                row.update(team=m.get('yes_sub_title'), code=code)
                                g['teams'][code] = m.get('yes_sub_title')
                            elif key == 'spread':
                                mt = re.match(r'^(.*?) wins by over ([\d.]+)', m.get('title') or m.get('yes_sub_title') or '')
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
    if errors and not games: sys.exit(1)

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'kalshi.json')
