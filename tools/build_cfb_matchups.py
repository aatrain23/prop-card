"""Build cfb_matchups.json (the info-only "Matchup" panel in the Line Shop) from this season's
play-by-play team stats and this week's games.

Usage: python3 -I tools/build_cfb_matchups.py WORKDIR cfb_matchups.json [--season 2026]

WORKDIR is the weekly model folder: sched_{season}.csv, x/adv_team_{season}.parquet and
cfb_lines.csv (this week's games). Every unit is rated opponent-adjusted (offense and defense
effects fit together, shrunk toward average), then each game is shown unit vs unit.
Information only: in a 2021-26 backtest these matchup edges did not beat closing spreads,
totals or team totals.
"""
import json, sys, datetime
import numpy as np, pandas as pd

D, OUT = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
Y = int(args[args.index('--season') + 1]) if '--season' in args else datetime.date.today().year - (datetime.date.today().month < 7)

# metric: (label, higher-is-better-for-offense)
MET = {'rush_epa': True, 'pass_epa': True, 'sr_rush': True, 'sr_pass': True, 'pass_rate': None,
       'plays': None, 'expl': True, 'stuff': False, 'sack': False}

s = pd.read_csv(f'{D}/sched_{Y}.csv', low_memory=False)
s = s[(s.completed == True) & s.home_points.notna()]
a = pd.read_parquet(f'{D}/x/adv_team_{Y}.parquet')
a['pos_team_id'] = pd.to_numeric(a.pos_team_id); a['game_id'] = pd.to_numeric(a.game_id)
a['rush_epa'] = a.EPA_rushing_per_play; a['pass_epa'] = a.EPA_passing_per_play
a['pass_rate'] = a.passes / (a.passes + a.rushes); a['plays'] = a.scrimmage_plays
a['sr_rush'] = a.rushing_first_downs_created_rate; a['sr_pass'] = a.passing_first_downs_created_rate
a['expl'] = a.EPA_explosive_rate; a['stuff'] = a.rushing_stuff_rate; a['sack'] = -a.sack_yards / a.passes.clip(lower=1)   # sack yards lost per pass
a = a[['game_id', 'pos_team_id'] + list(MET)]
g = s[['game_id', 'home_id', 'away_id', 'neutral_site', 'home_division', 'away_division']]
h = g.merge(a.rename(columns={'pos_team_id': 'home_id'}), on=['game_id', 'home_id'])
w = g.merge(a.rename(columns={'pos_team_id': 'away_id'}), on=['game_id', 'away_id'])
L = pd.concat([h.assign(off=h.home_id, de=h.away_id, ha=np.where(h.neutral_site, 0, 1)),
               w.assign(off=w.away_id, de=w.home_id, ha=np.where(w.neutral_site, 0, -1))]).dropna(subset=list(MET))
fbs = set(s.loc[s.home_division == 'fbs', 'home_id']) | set(s.loc[s.away_division == 'fbs', 'away_id'])
L['off'] = np.where(L.off.isin(fbs), L.off, -1); L['de'] = np.where(L.de.isin(fbs), L.de, -1)
t = sorted(set(L.off) | set(L.de)); ix = {k: i for i, k in enumerate(t)}; n = len(t)
A = np.zeros((len(L), 2 * n + 2)); r = np.arange(len(L))
A[r, [ix[k] for k in L.off]] = 1; A[r, [n + ix[k] for k in L.de]] = 1; A[:, 2 * n] = 1; A[:, 2 * n + 1] = L.ha.values
AtA = A.T @ A + np.diag(np.r_[np.full(2 * n, 4.0), 1e-6, 1e-6])
R = {}
for m in MET:
    b = np.linalg.solve(AtA, A.T @ L[m].values)
    R[m] = dict(o=dict(zip(t, b[:n])), d=dict(zip(t, b[n:2 * n])), mu=float(b[2 * n]))

name = dict(zip(s.home_id, s.home_team)) | dict(zip(s.away_id, s.away_team))
idx = {v: k for k, v in name.items()}
F = [k for k in t if k in fbs]
def ranks(m, side):
    v = R[m][side]; good = MET[m]
    # offense: best = highest (or lowest for stuff/sack); defense: best = allows least
    key = (lambda k: -v[k]) if (good is True) == (side == 'o') else (lambda k: v[k])
    return {k: i + 1 for i, k in enumerate(sorted(F, key=key))}
RK = {(m, sd): ranks(m, sd) for m in MET if MET[m] is not None for sd in ('o', 'd')}
rnd = lambda x, k=3: None if x is None else round(float(x), k)

def unit(o, d):
    out = {}
    for m, good in MET.items():
        proj = R[m]['o'][o] + R[m]['d'][d] + R[m]['mu']
        e = dict(proj=rnd(proj), avg=rnd(R[m]['mu']), own=rnd(R[m]['o'][o] + R[m]['mu']))
        if good is not None:
            e['o_rank'] = RK[(m, 'o')][o]; e['d_rank'] = RK[(m, 'd')][d]
        out[m] = e
    return out

lines = pd.read_csv(f'{D}/cfb_lines.csv')
games = []
for x in lines.itertuples():
    ia, ih = idx.get(x.away), idx.get(x.home)
    if ia not in ix or ih not in ix or ia not in fbs or ih not in fbs:
        continue
    games.append(dict(away=x.away, home=x.home, away_off=unit(ia, ih), home_off=unit(ih, ia)))

# spread of FBS offenses on each metric, to size edges
MSD = {m: rnd(np.std([R[m]['o'][k] for k in F])) for m in MET}
json.dump({'season': Y, 'msd': MSD, 'updated': datetime.date.today().isoformat(), 'fbs_teams': len(F),
           # spread of results around a line (2023-26 closing lines): margin, game total, team total
           'sd': {'margin': 15.2, 'total': 15.7, 'team_total': 11.0},
           'note': 'Information only: these matchup edges did not beat closing lines in a 2021-26 backtest.',
           'games': games}, open(OUT, 'w'), separators=(',', ':'))
print(len(games), 'games written of', len(lines))
