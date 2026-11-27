#!/usr/bin/env python3
"""Build experts.json: which Action Network and SportsLine analysts may appear on the site.

Rule (Aidan, Nov 24 2026: "only include them in github if they're profitable for either CFB, NFL, UFC, or a combination"):
an analyst is kept if their record is profitable (units > 0) in CFB, NFL or UFC on at least MIN graded picks,
or if CFB + NFL + UFC added together is profitable on at least MIN picks. Everyone else, and any analyst
not in the list (no record found), is left off the pages.

usage: python3 -I tools/build_experts.py tools/experts_raw.json experts.json [tools/nfl_prop_records.json [tools/nfl_ml_records.json [tools/cfb_records.json [tools/bettype_records.json [tools/propstat_records.json]]]]]

NFL player props by prop type (Aidan, Nov 27 2026: "prop-type record only"): tools/propstat_records.json, each analyst's Action
Network record on that prop type alone (receiving yards, receptions, TDs, ...), kept if up in units on at least 50 graded picks of
it. experts.js expertPropStatOk(stat, src, name, user). SportsLine analysts keep the overall NFL prop list (their prop history by
type couldn't be read). Backtest: see propstat_records.json "backtest".

Per bet type (Aidan, Nov 27 2026: "only show if they're profitable at that particular bet type"; he chose the best-tested list
for each bet type, and kept UFC as it was): tools/bettype_records.json says which list each CFB / NFL bet type uses (see its
"rules" and "backtest"). CFB spreads: analysts up on their CFB spread record; CFB totals, moneylines, team totals: the CFB list;
NFL moneylines and team totals: analysts up on their NFL game-line record; NFL spreads and totals: no analysts (no list beat the
vig); NFL props: the NFL prop list. experts.js expertBetOk(sport, market, src, name, user) applies it; UFC keeps expertOk.

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


def main(src, dst, propf=None, mlf=None, cfbf=None, btf=None, psf=None):
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
    if btf:
        bt = json.load(open(btf))
        out['bytype'] = {'through': bt['through'], 'min_picks': bt['min_picks'], 'rules': bt['rules'], 'backtest': bt['backtest'], 'lists': {}}
        for ln, L in bt['lists'].items():
            out['bytype']['lists'][ln] = {'an_users': {u.lower(): norm(n) for u, n in L.get('an_users', {}).items()},
                                          **{k: {norm(n): {'name': n, 'ok': r[0] + r[1] >= bt['min_picks'] and r[3] > 0, 'rec': r} for n, r in L[k].items()} for k in ('an', 'sl')}}
    if psf and 'bytype' in out:
        ps = json.load(open(psf))
        out['bytype']['propstat'] = {'through': ps['through'], 'min_picks': ps['min_picks'], 'backtest': ps['backtest'], 'stats': {
            st: {'an_users': {u.lower(): norm(n) for u, n in L['an_users'].items()},
                 'an': {norm(n): {'name': n, 'ok': r[0] + r[1] >= ps['min_picks'] and r[3] > 0, 'rec': r} for n, r in L['an'].items()}}
            for st, L in ps['stats'].items()}}
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
    if 'bytype' in out:
        keep['bytype'] = {'rules': out['bytype']['rules'], 'lists': {ln: {'an': {n: int(v['ok']) for n, v in L['an'].items()}, 'sl': {n: int(v['ok']) for n, v in L['sl'].items()}, 'users': L['an_users']}
                                                                     for ln, L in out['bytype']['lists'].items()}}
        if 'propstat' in out['bytype']:
            keep['bytype']['propstat'] = {st: {'an': {n: int(v['ok']) for n, v in L['an'].items()}, 'users': L['an_users']}
                                          for st, L in out['bytype']['propstat']['stats'].items()}
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
          "};\n"
          "// Per bet type (Aidan, Nov 27 2026): sport 'cfb' / 'nfl' / 'ufc', market 'spread' / 'total' / 'moneyline' / 'teamtotal' / 'prop'.\n"
          "// Each CFB / NFL bet type uses the analyst list that backtested best for it (EXPERTS.bytype.rules); a null rule shows no analysts.\n"
          "// UFC and anything without a rule keep expertOk.\n"
          "window.expertBetOk = (sport, market, src, name, user, stat) => {\n"
          "  const B = (window.EXPERTS || {}).bytype, R = B && B.rules[sport];\n"
          "  if (!R || !(market in R)) return sport === 'cfb' && window.expertCfbOk ? window.expertCfbOk(src, name, user) : window.expertOk(src, name, user);\n"
          "  const ln = R[market]; if (!ln) return false;\n"
          "  if (ln === 'cfb') return window.expertCfbOk(src, name, user);\n"
          "  if (ln === 'nflprop') return window.expertPropOk(src, name);\n"
          "  if (ln === 'propstat') return window.expertPropStatOk(stat, src, name, user);\n"
          "  const P = B.lists[ln]; if (!P) return false;\n"
          "  let n = String(name || ''); const m = /\\s*\\((Action Network|SportsLine)\\)\\s*$/.exec(n);\n"
          "  if (m) { src = src || m[1]; n = n.slice(0, m.index); }\n"
          "  const s = /^(an|action)/i.test(src || '') ? 'an' : /^(sl|sports)/i.test(src || '') ? 'sl' : '';\n"
          "  const k = window.expertNorm(n), u = String(user || '').toLowerCase();\n"
          "  if ((!s || s === 'an') && u && P.users[u] && P.an[P.users[u]] != null) return !!P.an[P.users[u]];\n"
          "  return (s ? [s] : ['an', 'sl']).some(x => !!P[x][k]);\n"
          "};\n"
          "// NFL player props by prop type (Aidan, Nov 27 2026: 'prop-type record only'): Action Network analysts up on their record for that\n"
          "// prop type (50+ picks). stat: a Line Shop key (recyds) or a board label ('receiving yards', 'Anytime TD'). SportsLine analysts keep\n"
          "// the overall NFL prop list (their history by prop type couldn't be read). Unknown prop types show no Action Network analysts.\n"
          "window.propStatKey = st => { const s = String(st || '').toLowerCase().replace(/[^a-z+ ]/g, ' ').replace(/\\s+/g, ' ').trim();\n"
          "  const M = {'receiving yards':'recyds', 'rec yds':'recyds', 'recyds':'recyds', 'rushing yards':'rushyds', 'rush yds':'rushyds', 'rushyds':'rushyds',\n"
          "    'passing yards':'passyds', 'pass yds':'passyds', 'passyds':'passyds', 'receptions':'rec', 'rec':'rec', 'pass completions':'comp', 'completions':'comp', 'comp':'comp',\n"
          "    'pass attempts':'passatt', 'passing attempts':'passatt', 'passatt':'passatt', 'rush attempts':'rushatt', 'rushing attempts':'rushatt', 'rushatt':'rushatt',\n"
          "    'tackles + assists':'tkl', 'tackles assists':'tkl', 'tkl':'tkl', 'anytime td':'td', 'touchdowns':'td', 'td':'td', 'passing tds':'passtd', 'pass tds':'passtd', 'passtd':'passtd',\n"
          "    'rush + rec yards':'rryds', 'rush rec yds':'rryds', 'rryds':'rryds', 'interceptions':'int', 'int':'int', 'longest reception':'longrec', 'longrec':'longrec', 'longest rush':'longrush', 'longrush':'longrush'};\n"
          "  if (M[s] || M[s.replace(/ \\+ /g, ' ')]) return M[s] || M[s.replace(/ \\+ /g, ' ')];\n"
          "  // free text (a pick's play, e.g. 'K.Shakir 5+ Receptions Yes'): first match wins; first-TD and combined pass + rush props have no list\n"
          "  const R = [[/first touchdown|pass \\+ rush|pass rush yds/, null], [/rush \\+ rec|rush rec|rushing \\+ receiving/, 'rryds'], [/longest rec/, 'longrec'], [/longest rush/, 'longrush'],\n"
          "    [/receiving yards|rec yds/, 'recyds'], [/rushing yards|rush yds/, 'rushyds'], [/passing yards|pass yds/, 'passyds'], [/receptions/, 'rec'], [/completions/, 'comp'],\n"
          "    [/pass(ing)? attempts/, 'passatt'], [/rush(ing)? attempts|carries/, 'rushatt'], [/tackles/, 'tkl'], [/pass(ing)? tds?|passing touchdowns/, 'passtd'],\n"
          "    [/interception|\\bint\\b/, 'int'], [/touchdown|\\btds?\\b/, 'td']];\n"
          "  for (const [re, k] of R) if (re.test(s)) return k;\n"
          "  return null; };\n"
          "window.expertPropStatOk = (stat, src, name, user) => {\n"
          "  const PS = ((window.EXPERTS || {}).bytype || {}).propstat; if (!PS) return window.expertPropOk(src, name);\n"
          "  let n = String(name || ''); const m = /\\s*\\((Action Network|SportsLine)\\)\\s*$/.exec(n);\n"
          "  if (m) { src = src || m[1]; n = n.slice(0, m.index); }\n"
          "  const s = /^(an|action)/i.test(src || '') ? 'an' : /^(sl|sports)/i.test(src || '') ? 'sl' : '';\n"
          "  const k = window.expertNorm(n), u = String(user || '').toLowerCase(), L = PS[window.propStatKey(stat)];\n"
          "  const P = (window.EXPERTS || {}).nflprop || { sl: {} };\n"
          "  if (s === 'sl' || (!s && P.sl[k] != null && !(L && (L.an[k] != null)))) return !!P.sl[k];\n"
          "  if (!L) return false;\n"
          "  if (u && L.users[u] && L.an[L.users[u]] != null) return !!L.an[L.users[u]];\n"
          "  return !!L.an[k];\n"
          "};\n")
    open(dst.replace('.json', '.js'), 'w').write(js)
    for k in ('an', 'sl'):
        keep = [v['name'] for v in out[k].values() if v['ok']]
        drop = [v['name'] for v in out[k].values() if not v['ok']]
        print(f'{k}: keep {len(keep)}, drop {len(drop)}')
        print('  keep:', ', '.join(keep))
        print('  drop:', ', '.join(drop))


if __name__ == '__main__':
    main(*sys.argv[1:8])
