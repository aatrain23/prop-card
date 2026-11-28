"""Gameday lines for the CFB model (Nov 27 2026, Aidan): every 15 minutes until kickoff, save each model game's market line
(the most common spread and total at FanDuel, BetMGM, Caesars and Fanatics, from Action Network's public odds, as on the Line Shop),
with the model's numbers at that time; once a game is final, save the score. CFB Team Grades' Model bets tab grades each model bet
twice from this: on Tuesday's line (when the model ran) and on the gameday line (the last one saved before kickoff).

usage: python3 tools/cfb_gameday.py <existing gameday.json or missing> <out gameday.json>"""
import json, re, sys, time, unicodedata, urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta

BOOKS = [69, 75, 49, 2988]
ALIAS = {'app state': 'appalachian state', 'ul monroe': 'louisiana monroe', 'florida international': 'fiu', 'uconn': 'connecticut',
         'umass': 'massachusetts', 'sam houston': 'sam houston state'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '').lower())
    s = ''.join(c for c in s if not unicodedata.combining(c)).replace('&', ' and ')
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', s)).strip()


def nn(s):
    return norm(re.sub(r"['’.]", '', str(s or '')))


def name_match(t, name):  # same rule as the CFB Grades page and the Line Shop
    n = nn(name); a = ALIAS.get(n)
    cands = [nn(t.get(k)) for k in ('display_name', 'location', 'full_name', 'short_name', 'abbr') if t.get(k)]
    full = nn(t.get('full_name'))
    return any(x == n or (a and x == a) or ALIAS.get(x) == n for x in cands) or full.startswith(n + ' ') or bool(a and full.startswith(a + ' '))


def get(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (cfb-gameday)', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if i == 2: raise
            time.sleep(3)


def mode(vals):
    vals = [v for v in vals if v is not None]
    if not vals: return None
    c = Counter(vals); top = max(c.values())
    return min(v for v in c if c[v] == top)


def consensus(g):
    hs, ts = [], []
    for b in BOOKS:
        ev = ((g.get('markets') or {}).get(str(b)) or (g.get('markets') or {}).get(b) or {}).get('event') or {}
        h = next((x for x in ev.get('spread') or [] if not x.get('is_live') and x.get('team_id') == g['home_team_id']), None)
        if h: hs.append(h.get('value'))
        o = next((x for x in ev.get('total') or [] if not x.get('is_live') and x.get('side') == 'over'), None)
        if o: ts.append(o.get('value'))
    return mode(hs), mode(ts)


def main(prev_path, out_path):
    now = datetime.now(timezone.utc)
    try:
        prev = json.load(open(prev_path))
    except Exception:
        prev = {'games': []}
    store = {g['key']: g for g in prev.get('games', [])}
    model = json.load(open('cfb_model.json'))
    week = model.get('week')
    an, errs = {}, []
    for d in range(-7, 8):
        day = (now + timedelta(days=d)).astimezone(timezone(timedelta(hours=-5))).strftime('%Y%m%d')
        try:
            j = get(f'https://api.actionnetwork.com/web/v2/scoreboard/ncaaf?bookIds={",".join(map(str, BOOKS))}&date={day}')
            for g in j.get('games', []): an[g['id']] = g
        except Exception as e:
            errs.append(f'{day}: {e}')
    if not an:
        print('no Action Network games', errs[:3]); sys.exit(1)
    seen = 0
    for m in model.get('games', []):
        g = next((x for x in an.values() if (lambda a, h: a and h and name_match(a, m['away']) and name_match(h, m['home']))(
            next((t for t in x['teams'] if t['id'] == x['away_team_id']), None), next((t for t in x['teams'] if t['id'] == x['home_team_id']), None))), None)
        if not g: continue
        seen += 1
        key = f"{model.get('updated', '')[:4] or now.year}-{week}|{m['away']}|{m['home']}"
        e = store.setdefault(key, {'key': key, 'week': week, 'away': m['away'], 'home': m['home']})
        e['an_id'] = g['id']; e['start'] = g['start_time']
        # Tuesday: the model run's own line, numbers and grades (kept as first seen)
        for k, v in (('tue_home', m.get('tue_home')), ('tue_total', m.get('tue_total')), ('tue_model_home', m.get('model_home')),
                     ('tue_model_total', m.get('model_total')), ('tue_grade', m.get('grade')), ('tue_total_grade', m.get('total_grade'))):
            e.setdefault(k, v)
        started = now >= datetime.fromisoformat(g['start_time'].replace('Z', '+00:00')) or g.get('status') in ('inprogress', 'complete')
        if not started:   # gameday: keep updating until kickoff
            h, t = consensus(g)
            if h is not None: e['close_home'] = h
            if t is not None: e['close_total'] = t
            e['close_at'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
            e['model_home'] = m.get('model_home'); e['model_total'] = m.get('model_total')
        if g.get('status') == 'complete' and e.get('close_home') is None:
            # finished before this job saw it pre-game: the books' pre-game lines are still in the feed, but one book can show an
            # in-game number, so take the middle value across the books
            hs, ts = [], []
            for bk in BOOKS:
                ev = ((g.get('markets') or {}).get(str(bk)) or {}).get('event') or {}
                h = next((x for x in ev.get('spread') or [] if not x.get('is_live') and x.get('team_id') == g['home_team_id']), None)
                if h and h.get('value') is not None: hs.append(h['value'])
                o = next((x for x in ev.get('total') or [] if not x.get('is_live') and x.get('side') == 'over'), None)
                if o and o.get('value') is not None: ts.append(o['value'])
            med = lambda v: sorted(v)[(len(v) - 1) // 2] if v else None
            e['close_home'], e['close_total'], e['close_src'] = med(hs), med(ts), 'final feed'
            e.setdefault('model_home', m.get('model_home')); e.setdefault('model_total', m.get('model_total'))
        if g.get('status') == 'complete':
            b = g.get('boxscore') or {}
            if b.get('total_home_points') is not None:
                e['final_away'] = b.get('total_away_points'); e['final_home'] = b.get('total_home_points')
    out = {'updated': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'week': week, 'errors': errs[:5],
           'games': sorted(store.values(), key=lambda x: (x.get('week') or 0, x.get('start') or '', x['key']))}
    json.dump(out, open(out_path, 'w'), separators=(',', ':'))
    print(f'{seen} model games matched; {len(out["games"])} saved; {len(errs)} fetch errors')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
