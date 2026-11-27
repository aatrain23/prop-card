#!/usr/bin/env python3
"""Rebuild tools/cfb_records.json: each analyst's college football record, for the CFB-only analyst list (experts.js expertCfbOk).

Action Network: every pre-game CFB spread, total, moneyline and team total pick (full game, first half and first quarter;
no live picks, no props) from the public scoreboard picks API, 2022 season on, graded by Action Network. 1 unit risked at
the posted price. SportsLine: each expert's CFB record from tools/experts_raw.json (every graded pick SportsLine lists since 2016).
Records are [W, L, P, units]. Read-only public data.

usage: python3 tools/cfb_records.py tools/experts_raw.json tools/cfb_records.json
Run weekly by .github/workflows/cfb-analysts.yml, which then rebuilds experts.json / experts.js with tools/build_experts.py.
"""
import json, re, sys, time, urllib.request
from datetime import datetime, timezone

URL = 'https://api.actionnetwork.com/web/v2/scoreboard/picks/ncaaf?season={s}&week={w}&division=FBS'
MARKET = [(re.compile(r'^spread_'), 'spread'), (re.compile(r'^(over|under)$'), 'total'), (re.compile(r'^ml_'), 'moneyline'),
          (re.compile(r'^(home|away)_(over|under)$'), 'teamtotal')]


def get(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (cfb-records)', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == 3: raise
            time.sleep(3 + 4 * attempt)


def ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def main(raw_path, out_path):
    now = datetime.now(timezone.utc)
    seen, rec, names, errors = set(), {}, {}, []
    last_season = now.year if now.month >= 8 else now.year - 1
    for s in range(2022, last_season + 1):
        for w in range(0, 21):
            try:
                d = get(URL.format(s=s, w=w))
            except Exception as e:
                errors.append(f'{s} wk {w}: {e}'); continue
            for g in d.get('games') or []:
                start = ts(g.get('start_time'))
                for e in g.get('experts') or []:
                    user = (e.get('username') or '').lower()
                    if not user: continue
                    for p in e.get('picks') or []:
                        if p.get('id') in seen or p.get('game_id') != g.get('id'): continue
                        seen.add(p.get('id'))
                        if p.get('is_live') or p.get('period') not in ('game', 'firsthalf', 'firstquarter'): continue
                        if p.get('result') not in ('win', 'loss', 'push'): continue
                        if not any(rx.match(str(p.get('type') or '')) for rx, _ in MARKET): continue
                        made = ts(p.get('created_at'))
                        if start and made and made > start: continue
                        try: o = float(p.get('odds'))
                        except (TypeError, ValueError): continue
                        if not o: continue
                        u = (o / 100 if o > 0 else 100 / -o) if p['result'] == 'win' else (-1.0 if p['result'] == 'loss' else 0.0)
                        r = rec.setdefault(user, [0, 0, 0, 0.0])
                        r[{'win': 0, 'loss': 1, 'push': 2}[p['result']]] += 1
                        r[3] += u
                        names[user] = (e.get('name') or user).strip()
            time.sleep(0.3)
    if not rec:
        print('no picks read:', errors[:3]); sys.exit(1)
    raw = json.load(open(raw_path))
    out = {'through': now.strftime('%Y-%m-%d'), 'min_picks': 50,
           'note': 'College football picks only, 1 unit risked at the posted price. Action Network: every pre-game spread, total, '
                   'moneyline and team total pick (full game, first half and first quarter) from the scoreboard picks API, 2022 on, '
                   'graded by Action Network. SportsLine: every graded CFB pick SportsLine lists since 2016 (from experts_raw.json). '
                   'Records [W, L, P, units]. Rebuilt weekly by tools/cfb_records.py.',
           'an': {}, 'an_users': {}, 'sl': {n: r['cfb'] for n, r in raw['sl'].items() if 'cfb' in r}, 'errors': errors}
    for user, r in rec.items():
        name = names[user]
        if name in out['an'] and out['an_users'].get(user) != name:
            name = f'{name} ({user})'
        out['an'][name] = [r[0], r[1], r[2], round(r[3], 2)]
        out['an_users'][user] = name
    json.dump(out, open(out_path, 'w'), ensure_ascii=False, indent=0)
    ok = sum(1 for r in out['an'].values() if r[0] + r[1] >= 50 and r[3] > 0)
    print(len(seen), 'picks read;', len(rec), 'analysts;', ok, 'profitable with 50+;', len(errors), 'errors', errors[:3])


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'tools/experts_raw.json', sys.argv[2] if len(sys.argv) > 2 else 'tools/cfb_records.json')
