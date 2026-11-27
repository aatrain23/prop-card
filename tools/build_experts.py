#!/usr/bin/env python3
"""Build experts.json: which Action Network and SportsLine analysts may appear on the site.

Rule (Aidan, Nov 24 2026: "only include them in github if they're profitable for either CFB, NFL, UFC, or a combination"):
an analyst is kept if their record is profitable (units > 0) in CFB, NFL or UFC on at least MIN graded picks,
or if CFB + NFL + UFC added together is profitable on at least MIN picks. Everyone else, and any analyst
not in the list (no record found), is left off the pages.

usage: python3 -I tools/build_experts.py tools/experts_raw.json experts.json [tools/nfl_prop_records.json [tools/nfl_ml_records.json [tools/cfb_records.json]]]

College football (Aidan, Nov 27 2026: "make sure we're only using profitable CFB analysts"): CFB picks (Line Shop, College
football page) use their own list from each analyst's CFB record alone (tools/cfb_records.json, built by
tools/cfb_records.py), kept if up in units on at least CFB_MIN graded CFB picks. Walk-forward backtest, Action Network CFB picks
2022 - 2026 wk 12 (each pick judged only on the analyst's record before that day): CFB-profitable analysts +2.7% on 12,895 picks
(+7.5% on 441 first half / first quarter picks), vs +1.7% for the general list (which looks ahead) and +0.4% for everyone; the
general list's analysts who weren't CFB-profitable were -0.8% on 9,047 picks.

NFL player props (Aidan, Nov 26 2026: "profitable betters only", for the pre-game board and the Line Shop): a separate,
stricter list from each analyst's NFL player-prop record alone (Action Network 2023 on, SportsLine 2022 on; 1 unit risked
at the posted price; built by the props backtest into tools/nfl_prop_records.json). Kept if up in units on at least
PROP_MIN graded prop picks. Backtest 2023 - 2026 wk 11 (profitable-to-date analysts, no analyst on the other side,
model edge > 0, the 4 Unders): +14.4% on 426 bets, vs +11.7% on 1,085 with every analyst.

NFL moneylines (Aidan, Nov 26 2026, after a per-bet-type backtest): their own list from each analyst's NFL moneyline record
alone (tools/nfl_ml_records.json), kept if up in units on at least ML_MIN graded moneyline picks. Backtest 2023 - 2026 wk 12
(walk-forward, distinct bets at the best posted price): moneyline-profitable analysts +4.7% on 449 bets, and +12.5% on 141 with
no analyst on the other team, vs +3.2% on 847 for the general list. Spreads and totals: no analyst list beat the vig, so those
keep the general list.
"""
import json, re, sys, unicodedata

MIN = 20
PROP_MIN = 50
ML_MIN = 50
CFB_MIN = 50
SPORTS = ('cfb', 'nfl', 'ufc')


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', s.lower())


def judge(rec):
    good, tot_u, tot_n = [], 0.0, 0
    for sp in SPORTS:
        r = rec.get(sp)
        if not r:
            continue
        n = r[0] + r[1]
        tot_u += r[3]; tot_n += n
        if n >= MIN and r[3] > 0:
            good.append(sp)
    combo = tot_n >= MIN and tot_u > 0
    return (bool(good) or combo), good, round(tot_u, 2), tot_n


def main(src, dst, propf=None, mlf=None, cfbf=None):
    raw = json.load(open(src))
    out = {'updated': raw['pulled'], 'min_picks': MIN,
           'rule': f'Kept if profitable in CFB, NFL or UFC (at least {MIN} graded picks), or across the three combined. '
                   'Analysts not listed (no record found) are left off.',
           'notes': raw['notes'], 'an': {}, 'sl': {}, 'an_users': {}}
    for name, user, rec in raw['an']:
        ok, good, u, n = judge(rec)
        e = {'name': name.strip(), 'user': user, 'ok': ok, 'profitable_in': good, 'combined_units': u, 'combined_picks': n, 'rec': rec}
        out['an'][norm(name)] = e
        out['an_users'][user.lower()] = norm(name)
    for name, rec in raw['sl'].items():
        ok, good, u, n = judge(rec)
        out['sl'][norm(name)] = {'name': name, 'ok': ok, 'profitable_in': good, 'combined_units': u, 'combined_picks': n, 'rec': rec}
    if propf:
        pr = json.load(open(propf))
        out['nflprop'] = {'through': pr['through'], 'min_picks': PROP_MIN,
                          'rule': f'NFL player props: kept if up in units on at least {PROP_MIN} graded NFL prop picks (records through {pr["through"]}).',
                          'an': {}, 'sl': {}}
        for k in ('an', 'sl'):
            for name, r in pr[k].items():
                out['nflprop'][k][norm(name)] = {'name': name, 'ok': r[0] + r[1] >= PROP_MIN and r[3] > 0, 'rec': r}
    if mlf:
        ml = json.load(open(mlf))
        out['nflml'] = {'through': ml['through'], 'min_picks': ML_MIN,
                        'rule': f'NFL moneylines: kept if up in units on at least {ML_MIN} graded NFL moneyline picks (records through {ml["through"]}).',
                        'an': {}, 'sl': {}, 'an_users': {u: norm(n) for u, n in ml.get('an_users', {}).items()}}
        for k in ('an', 'sl'):
            for name, r in ml[k].items():
                out['nflml'][k][norm(name)] = {'name': name, 'ok': r[0] + r[1] >= ML_MIN and r[3] > 0, 'rec': r}
    if cfbf:
        cf = json.load(open(cfbf))
        out['cfb'] = {'through': cf['through'], 'min_picks': CFB_MIN,
                      'rule': f'College football: kept if up in units on at least {CFB_MIN} graded CFB picks (records through {cf["through"]}).',
                      'an': {}, 'sl': {}, 'an_users': {u.lower(): norm(n) for u, n in cf.get('an_users', {}).items()}}
        for k in ('an', 'sl'):
            for name, r in cf[k].items():
                out['cfb'][k][norm(name)] = {'name': name, 'ok': r[0] + r[1] >= CFB_MIN and r[3] > 0, 'rec': r}
    json.dump(out, open(dst, 'w'), ensure_ascii=False, indent=0)
    # experts.js: the same list for the pages, loaded synchronously (<script src="experts.js">) so filtering never waits on a fetch
    keep = {'an': {k: int(v['ok']) for k, v in out['an'].items()}, 'sl': {k: int(v['ok']) for k, v in out['sl'].items()},
            'users': out['an_users'], 'updated': out['updated'], 'rule': out['rule']}
    if 'nflprop' in out:
        keep['nflprop'] = {k: {n: int(v['ok']) for n, v in out['nflprop'][k].items()} for k in ('an', 'sl')}
    if 'nflml' in out:
        keep['nflml'] = {k: {n: int(v['ok']) for n, v in out['nflml'][k].items()} for k in ('an', 'sl')}
        keep['nflml']['users'] = out['nflml']['an_users']
    if 'cfb' in out:
        keep['cfb'] = {k: {n: int(v['ok']) for n, v in out['cfb'][k].items()} for k in ('an', 'sl')}
        keep['cfb']['users'] = out['cfb']['an_users']
    js = ("// Generated by tools/build_experts.py from experts.json. Do not edit by hand.\n"
          "// Which Action Network / SportsLine analysts may show on these pages (profitable in CFB, NFL or UFC, or the three combined).\n"
          f"window.EXPERTS = {json.dumps(keep, ensure_ascii=False, separators=(',', ':'))};\n"
          "window.expertNorm = s => String(s || '').normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');\n"
          "// src: 'Action Network' / 'SportsLine' (or 'AN' / 'SL'); name may end in ' (Action Network)' / ' (SportsLine)'. Unknown analysts are left off.\n"
          "window.expertOk = (src, name, user) => {\n"
          "  const E = window.EXPERTS; let n = String(name || ''); const m = /\\s*\\((Action Network|SportsLine)\\)\\s*$/.exec(n);\n"
          "  if (m) { src = src || m[1]; n = n.slice(0, m.index); }\n"
          "  const s = /^(an|action)/i.test(src || '') ? 'an' : /^(sl|sports)/i.test(src || '') ? 'sl' : '';\n"
          "  const k = expertNorm(n), u = String(user || '').toLowerCase();\n"
          "  if ((!s || s === 'an') && u && E.users[u] && E.an[E.users[u]] != null) return !!E.an[E.users[u]];\n"
          "  const hits = (s ? [s] : ['an', 'sl']).map(x => E[x][k]).filter(v => v != null);\n"
          "  return hits.some(Boolean);\n"
          "};\n"
          "// NFL player props only (Aidan, Nov 26 2026): analysts up on their own NFL prop record (50+ picks). Unknown analysts are left off.\n"
          "window.expertPropOk = (src, name) => {\n"
          "  const P = (window.EXPERTS || {}).nflprop; if (!P) return window.expertOk(src, name);\n"
          "  let n = String(name || ''); const m = /\\s*\\((Action Network|SportsLine)\\)\\s*$/.exec(n);\n"
          "  if (m) { src = src || m[1]; n = n.slice(0, m.index); }\n"
          "  const s = /^(an|action)/i.test(src || '') ? 'an' : /^(sl|sports)/i.test(src || '') ? 'sl' : '';\n"
          "  const k = window.expertNorm(n);\n"
          "  return (s ? [s] : ['an', 'sl']).some(x => !!P[x][k]);\n"
          "};\n"
          "// NFL moneylines only (Aidan, Nov 26 2026): analysts up on their own NFL moneyline record (50+ picks). Unknown analysts are left off.\n"
          "window.expertMlOk = (src, name, user) => {\n"
          "  const P = (window.EXPERTS || {}).nflml; if (!P) return window.expertOk(src, name, user);\n"
          "  let n = String(name || ''); const m = /\\s*\\((Action Network|SportsLine)\\)\\s*$/.exec(n);\n"
          "  if (m) { src = src || m[1]; n = n.slice(0, m.index); }\n"
          "  const s = /^(an|action)/i.test(src || '') ? 'an' : /^(sl|sports)/i.test(src || '') ? 'sl' : '';\n"
          "  const k = window.expertNorm(n), u = String(user || '').toLowerCase();\n"
          "  if ((!s || s === 'an') && u && P.users[u] && P.an[P.users[u]] != null) return !!P.an[P.users[u]];\n"
          "  return (s ? [s] : ['an', 'sl']).some(x => !!P[x][k]);\n"
          "};\n"
          "// College football only (Aidan, Nov 27 2026): analysts up on their own CFB record (50+ picks). Unknown analysts are left off.\n"
          "window.expertCfbOk = (src, name, user) => {\n"
          "  const P = (window.EXPERTS || {}).cfb; if (!P) return window.expertOk(src, name, user);\n"
          "  let n = String(name || ''); const m = /\\s*\\((Action Network|SportsLine)\\)\\s*$/.exec(n);\n"
          "  if (m) { src = src || m[1]; n = n.slice(0, m.index); }\n"
          "  const s = /^(an|action)/i.test(src || '') ? 'an' : /^(sl|sports)/i.test(src || '') ? 'sl' : '';\n"
          "  const k = window.expertNorm(n), u = String(user || '').toLowerCase();\n"
          "  if ((!s || s === 'an') && u && P.users[u] && P.an[P.users[u]] != null) return !!P.an[P.users[u]];\n"
          "  return (s ? [s] : ['an', 'sl']).some(x => !!P[x][k]);\n"
          "};\n")
    open(dst.replace('.json', '.js'), 'w').write(js)
    for k in ('an', 'sl'):
        keep = [v['name'] for v in out[k].values() if v['ok']]
        drop = [v['name'] for v in out[k].values() if not v['ok']]
        print(f'{k}: keep {len(keep)}, drop {len(drop)}')
        print('  keep:', ', '.join(keep))
        print('  drop:', ', '.join(drop))


if __name__ == '__main__':
    main(*sys.argv[1:6])
