"""Discord alerts for games Aidan has bet (Nov 27 2026): every scoring play and every final in a game on his College football
or NFL bet card, with how each of his bets on that game stands. Reads the cards' published feed sheets and ESPN's public
scoreboard; posts to the Discord webhook in the DISCORD_WEBHOOK secret. Run every 5 minutes by .github/workflows/bet-alerts.yml.

usage: python3 tools/bet_alerts.py <state.json in> <state.json out>"""
import csv, io, json, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime, timezone, timedelta

CFB_FEED = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTHqNMre3mm5QcYdwBR4BrFavVzSPaDZUKKXdq4L_pLrgsXylKwTUm3dRDG7Iehzl7Moy2V6QTfaxIq/pub?output=csv'
NFL_FEED = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRFDjXnJ_DHrTGWyx9-s4oyjqhQHyQ2ZCoBw_Iwkm2ZP2RylC5r2nt_t9eIWGHy7rTfx0FFplBZOcb2/pub?gid=0&single=true&output=csv'
ESPN = {'cfb': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football',
        'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'}
ET = timezone(timedelta(hours=-5))
ALIAS = {'app state': 'appalachian state', 'ul monroe': 'louisiana monroe', 'florida international': 'fiu', 'uconn': 'connecticut',
         'umass': 'massachusetts', 'sam houston': 'sam houston state', 'miami oh': 'miami ohio'}
NFL_AB = {'LA': 'LAR', 'WAS': 'WSH', 'JAC': 'JAX'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '').lower())
    s = ''.join(c for c in s if not unicodedata.combining(c)).replace('&', ' and ')
    return re.sub(r'\s+', ' ', re.sub(r"[^a-z0-9 ]", ' ', re.sub(r"['’.]", '', s))).strip()


def get(url, js=True):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (bet-alerts)'})
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
                return json.loads(b) if js else b.decode('utf-8')
        except Exception:
            if i == 2: raise
            time.sleep(3)


def team_match(t, name, sport):
    """t: an ESPN competitor's team; name: as the bet card writes it (CFB full school name, NFL abbreviation)."""
    n = norm(name)
    if sport == 'nfl':
        ab = NFL_AB.get(name.strip().upper(), name.strip().upper())
        return t.get('abbreviation', '').upper() == ab
    a = ALIAS.get(n)
    cands = [norm(t.get(k)) for k in ('location', 'displayName', 'shortDisplayName', 'abbreviation', 'name') if t.get(k)]
    return any(x == n or (a and x == a) for x in cands) or norm(t.get('displayName')).startswith(n + ' ')


def team_score(t, name, sport):
    # 2 = exact name, 1 = only the start of the full name ("Texas" vs "Texas A&M Aggies"), 0 = no match
    if not team_match(t, name, sport): return 0
    if sport == 'nfl': return 2
    n = norm(name); a = ALIAS.get(n)
    cands = [norm(t.get(k)) for k in ('location', 'displayName', 'shortDisplayName', 'abbreviation', 'name') if t.get(k)]
    return 2 if any(x == n or (a and x == a) for x in cands) else 1


def side_of(ev, name, sport):
    # which team in this game the name means, by the better match (so "Texas" is Texas, not Texas A&M)
    sa, sh = team_score(ev['away']['team'], name, sport), team_score(ev['home']['team'], name, sport)
    return None if not (sa or sh) else 'away' if sa >= sh else 'home'


def post(hook, text):
    if hook == 'dry':   # test run: print instead of posting
        print('----\n' + text); return True
    data = json.dumps({'content': text[:1990], 'allowed_mentions': {'parse': []}}).encode()
    req = urllib.request.Request(hook, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'bet-alerts (prop-card, 1.0)'})
    for i in range(3):
        try:
            urllib.request.urlopen(req, timeout=30).read(); return True
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(float(json.loads(e.read() or b'{}').get('retry_after', 2)) + .5); continue
            print('discord error', e.code); return False
        except Exception as e:
            print('discord error', e); time.sleep(2)
    return False


def load_bets():
    """[(sport, away, home, bet)] for game bets on the two cards. bet: {text, type, side, line, ou, player}"""
    out = []
    try:
        for r in csv.DictReader(io.StringIO(get(CFB_FEED, js=False))):
            mu, txt = (r.get('matchup') or '').strip(), (r.get('bet') or '').strip()
            if not mu or not txt or (r.get('result') or '').strip(): continue
            for part in mu.split(' + '):
                m = re.match(r'^(.*?) (?:at|vs\.?) (.*)$', part.strip())
                if not m: continue
                multi = ' + ' in mu or (r.get('type') or '').startswith('Parlay')
                out.append(('cfb', m.group(1), m.group(2), {'text': txt, 'type': 'Parlay' if multi or txt.startswith('Parlay') else (r.get('type') or ''), 'side': r.get('side') or '',
                            'line': r.get('line') or '', 'ou': 'under' if re.search(r'\bunder\b', txt, re.I) else 'over'}))
    except Exception as e:
        print('CFB feed failed', e)
    try:
        for r in csv.DictReader(io.StringIO(get(NFL_FEED, js=False))):
            gm = (r.get('game') or '').strip()
            if not gm or (r.get('result') or '').strip(): continue
            m = re.match(r'^(\S+) @ (\S+)$', gm)
            if not m: continue
            stat, player = (r.get('stat') or '').strip(), (r.get('player') or '').strip()
            typ = {'Moneyline': 'Moneyline', 'Total': 'Total', 'Spread': 'Spread', 'Team Total': 'Team Total'}.get(stat, 'Prop')
            txt = player if typ != 'Prop' else f"{player} {r.get('side', '')} {r.get('line', '')} {stat}".replace('Over 0.5 Anytime TD', 'anytime TD')
            if typ == 'Total': txt = f"{r.get('side')} {r.get('line')}"
            out.append(('nfl', m.group(1), m.group(2), {'text': txt.strip(), 'type': typ, 'side': r.get('side') or r.get('team') or '', 'line': r.get('line') or '',
                        'ou': (r.get('side') or 'over').lower(), 'player': player if typ == 'Prop' else '', 'stat': stat}))
    except Exception as e:
        print('NFL feed failed', e)
    return out


def status(b, ev, sport):
    """How the bet stands at this score: ('W'|'L'|'P'|None, short text)"""
    if b['type'] == 'Parlay':   # the legs in this game: "Texas ML", "Air Force +7.5" (first half / quarter legs aren't tracked)
        res, txts = [], []
        for leg in re.sub(r'^Parlay:\s*', '', b['text']).split(' + '):
            m = re.match(r'^(?:(1H|1Q|2H)\s+)?(.+?)\s+(ML|[+-]\d+(?:\.\d+)?)$', leg.strip())
            if not m or not side_of(ev, m.group(2), sport): continue
            if m.group(1): txts.append(f"{leg.strip()}: not tracked by half"); continue
            r, t = status({'type': 'Moneyline' if m.group(3) == 'ML' else 'Spread', 'side': m.group(2), 'line': '' if m.group(3) == 'ML' else m.group(3),
                           'text': leg, 'ou': ''}, ev, sport)
            res.append(r); txts.append(f"{leg.strip()} leg {t}")
        r = 'L' if 'L' in res else ('W' if res and all(x == 'W' for x in res) else None)
        return r, '; '.join(txts)
    a, h = ev['away'], ev['home']; sa, sh = ev['away_score'], ev['home_score']
    typ, side, line = b['type'], b['side'], b['line']
    try: ln = float(str(line).replace('+', '')) if line not in ('', None) else None
    except ValueError: ln = None
    who = lambda name: side_of(ev, name, sport)
    if typ in ('Spread', 'Moneyline'):
        w = who(side)
        if not w: return None, ''
        d = (sa - sh) if w == 'away' else (sh - sa)
        c = d + (ln or 0) if typ == 'Spread' else d
        if typ == 'Moneyline': return ('W' if c > 0 else 'L' if c < 0 else 'P'), (f"winning by {c:g}" if c > 0 else f"down {-c:g}" if c < 0 else 'tied')
        return ('W' if c > 0 else 'L' if c < 0 else 'P'), (f"covering by {c:g}" if c > 0 else f"short by {-c:g}" if c < 0 else 'on the number')
    if typ == 'Total' and ln is not None:
        t = sa + sh; over = str(side).lower().startswith('o') or b['text'].lower().startswith('over')
        c = (t - ln) if over else (ln - t)
        import math
        need = math.floor(ln - t) + 1   # points still needed to go over
        txt = (f"{t} total, over by {t - ln:g}" if t > ln else f"{t} total, needs {need} more") if over else (f"{t} total, {ln - t:g} under" if t < ln else f"{t} total, over by {t - ln:g}")
        return ('W' if c > 0 else 'L' if c < 0 else 'P'), txt
    if typ == 'Team Total' and ln is not None:
        w = who(side)
        if not w: return None, ''
        t = sa if w == 'away' else sh; over = b['ou'] == 'over'
        c = (t - ln) if over else (ln - t)
        return ('W' if c > 0 else 'L' if c < 0 else 'P'), f"team has {t}"
    return None, ''


def main(sp, op):
    hook = 'dry' if os.environ.get('DRY_RUN') else os.environ.get('DISCORD_WEBHOOK', '').strip()
    try: state = json.load(open(sp))
    except Exception: state = {}
    if not hook:   # nothing to send to yet: keep the state as it is so nothing is skipped once the secret is added
        json.dump(state, open(op, 'w')); print('DISCORD_WEBHOOK secret is not set'); return
    try: state = json.load(open(sp))
    except Exception: state = {}
    state.setdefault('events', {})
    bets = load_bets()
    now = datetime.now(timezone.utc)
    days = sorted({(now.astimezone(ET) + timedelta(days=d)).strftime('%Y%m%d') for d in (-1, 0)})
    sent = 0
    for sport in ('cfb', 'nfl'):
        mine = [x for x in bets if x[0] == sport]
        if not mine: continue
        for day in days:
            try: sb = get(f"{ESPN[sport]}/scoreboard?dates={day}" + ('&groups=80&limit=400' if sport == 'cfb' else ''))
            except Exception as e: print(sport, day, 'scoreboard failed', e); continue
            for e in sb.get('events', []):
                comp = (e.get('competitions') or [{}])[0]; cs = comp.get('competitors') or []
                ca = next((c for c in cs if c.get('homeAway') == 'away'), None); ch = next((c for c in cs if c.get('homeAway') == 'home'), None)
                if not ca or not ch: continue
                eb = [b for (s, aw, hm, b) in mine if (team_match(ca['team'], aw, sport) and team_match(ch['team'], hm, sport)) or (team_match(ca['team'], hm, sport) and team_match(ch['team'], aw, sport))]
                if not eb: continue
                st = (comp.get('status') or e.get('status') or {}).get('type', {})
                if st.get('state') == 'pre': continue
                ev = {'away': ca, 'home': ch, 'away_score': int(float(ca.get('score') or 0)), 'home_score': int(float(ch.get('score') or 0))}
                an, hn = ca['team'].get('shortDisplayName') or ca['team'].get('location'), ch['team'].get('shortDisplayName') or ch['team'].get('location')
                key = f"{sport}:{e['id']}"
                s = state['events'].setdefault(key, {'plays': None, 'final': bool(st.get('completed')) and hook != 'dry'})   # already over when first seen: no alert
                score_line = f"{an} {ev['away_score']}, {hn} {ev['home_score']}"
                def bet_lines(final):
                    out = []
                    for b in eb:
                        r, txt = status(b, ev, sport)
                        icon = {'W': '✅', 'L': '❌', 'P': '➖'}.get(r, '•')
                        if final and b['type'] == 'Parlay': out.append(f"{icon} {b['text']}" + (f" — {'legs in this game won' if r == 'W' else 'a leg in this game lost'}" if r else ' — grades on your card'))
                        elif final: out.append(f"{icon} {b['text']}" + (f" — {'won' if r == 'W' else 'lost' if r == 'L' else 'push'}" if r else ' — grades on your card'))
                        else: out.append(f"{icon} {b['text']}" + (f" — {txt}" if txt else ''))
                    return '\n'.join(out)
                # scoring plays
                plays = None
                try:
                    summ = get(f"{ESPN[sport]}/summary?event={e['id']}")
                    plays = summ.get('scoringPlays') or []
                except Exception as ex: print('summary failed', e['id'], ex)
                if plays is not None:
                    if s['plays'] is None: s['plays'] = max(0, len(plays) - 2) if hook == 'dry' else len(plays)   # first look at this game: no backlog
                    for p in plays[s['plays']:]:
                        tm = (p.get('team') or {}).get('displayName') or ''
                        kind = (p.get('type') or {}).get('text') or 'Score'
                        clock = f"Q{(p.get('period') or {}).get('number', '')} {(p.get('clock') or {}).get('displayValue', '')}".strip()
                        sc = f"{an} {p.get('awayScore', ev['away_score'])}, {hn} {p.get('homeScore', ev['home_score'])}"
                        ev2 = dict(ev, away_score=int(p.get('awayScore', ev['away_score'])), home_score=int(p.get('homeScore', ev['home_score'])))
                        lines = []
                        for b in eb:
                            r, txt = status(b, ev2, sport)
                            if b.get('player') and b.get('stat', '').lower().startswith('anytime') and norm(b['player']).split()[-1] in norm(p.get('text')):
                                txt, r = 'scored \U0001F389', 'W'
                            lines.append(f"{ {'W': chr(0x2705), 'L': chr(0x274c), 'P': chr(0x2796)}.get(r, chr(0x2022)) } {b['text']}" + (f" — {txt}" if txt else ''))
                        msg = f"\U0001F3C8 **{kind} {tm}** ({clock})\n**{sc}**\n_{p.get('text', '')}_\n" + '\n'.join(lines)
                        if hook and post(hook, msg): sent += 1
                        s['plays'] += 1
                if st.get('completed') and not s['final']:
                    msg = f"\U0001F3C1 **FINAL: {score_line}**\n" + bet_lines(True)
                    if not hook or post(hook, msg): s['final'] = True; sent += 1
    # forget games older than a week
    state['updated'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    json.dump(state, open(op, 'w'), separators=(',', ':'))
    print(f'{len(bets)} open bets; {sent} alerts sent; webhook {"set" if hook else "MISSING"}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
