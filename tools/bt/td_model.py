"""Walk-forward anytime-TD model for backtesting (same formula as tools/nfl_grade_all.py build/grade_prop for 'atd'):
for each target season S, week W, only games before that week are used.
  m_td = weighted mean of (rush + rec TDs) over the player's last 24 regular-season games, weight 0.5**(age/6) x (1.0 this season, 0.6 earlier)
  players need 3+ games this season (as on the board), so weeks 1-3 have no picks
  opponent factor f = clamp(((opp allowed per game to the position / league avg) * k + 6) / (k + 6), 0.7, 1.35), this season before week W
  lam = 0.55 * m_td * f + 0.10 ; p = 1 - exp(-lam)
Result: 1 = scored a rush/rec TD, 0 = played (stats row or offensive snaps) and didn't, V = didn't play.
usage: python3 -I td_model.py data_dir out.csv
"""
import sys, re, math, unicodedata
import numpy as np, pandas as pd

ATD_A, ATD_B = 0.55, 0.10
TEAMFIX = {'JAC': 'JAX', 'LAR': 'LA', 'WSH': 'WAS', 'LV': 'LV', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}
tm = lambda t: TEAMFIX.get(t, t)


def norm(n):
    n = ''.join(c for c in unicodedata.normalize('NFD', n if isinstance(n, str) else '') if unicodedata.category(c) != 'Mn').lower()
    n = re.sub(r"[.'’`]", '', n); n = re.sub(r'[^a-z ]', ' ', n)
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return ' '.join(n.split())


d, out = sys.argv[1], sys.argv[2]
df = pd.concat([pd.read_csv(f'{d}/stats_{y}.csv', low_memory=False) for y in range(2022, 2027)], ignore_index=True)
df = df[df.season_type == 'REG'].copy()
for c in ['rushing_tds', 'receiving_tds']: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
df['td'] = df.rushing_tds + df.receiving_tds
df['pos'] = df.position_group.fillna(df.position)
df['team'] = df.team.map(tm); df['opponent_team'] = df.opponent_team.map(tm)
df['t'] = df.season * 100 + df.week
df['nm'] = df.player_display_name.map(norm)

g = pd.read_csv(f'{d}/games.csv', low_memory=False)
g = g[(g.game_type == 'REG') & (g.season >= 2023)]
OPP = {}
for r in g.itertuples():
    h, a = tm(r.home_team), tm(r.away_team)
    OPP[(r.season, r.week, h)] = a; OPP[(r.season, r.week, a)] = h

snaps = pd.concat([pd.read_parquet(f'{d}/snaps_{y}.parquet') for y in range(2023, 2027)], ignore_index=True)
snaps = snaps[(snaps.game_type == 'REG') & (snaps.offense_snaps > 0)]
PLAYED = set(zip(snaps.season, snaps.week, snaps.player.map(norm), snaps.team.map(tm)))
SCORED = {(r.season, r.week, r.nm): r.td for r in df.itertuples()}

targets = sorted({(s, w) for (s, w, _) in OPP})
last_t = int(df.t.max())
targets = [x for x in targets if x[0] * 100 + x[1] <= last_t]

# opponent factors per target
def factors(S, W):
    c = df[(df.season == S) & (df.week < W)]
    if c.empty: return {}
    al = c.groupby(['opponent_team', 'pos', 'week']).td.sum().reset_index()
    per = al.groupby(['opponent_team', 'pos']).td.mean(); n = al.groupby(['opponent_team', 'pos']).size(); lg = al.groupby('pos').td.mean()
    F = {}
    for (opp, pos), v in per.items():
        L = lg.loc[pos]; k = n[(opp, pos)]
        F[(opp, pos)] = float(min(1.35, max(0.7, ((v / L) * k + 6) / (k + 6)))) if L > 0 else 1.0
    return F
FAC = {x: factors(*x) for x in targets}

rows = []
sk = df[df.pos.isin(['QB', 'RB', 'WR', 'TE'])].sort_values('t')
for pid, gp in sk.groupby('player_id'):
    T = gp.t.values; X = gp.td.values.astype(float); SE = gp.season.values
    for (S, W) in targets:
        tt = S * 100 + W
        i = np.searchsorted(T, tt)   # games before target
        if i == 0: continue
        if (SE[:i] == S).sum() < 3: continue
        last = gp.iloc[i - 1]
        team = last.team; opp = OPP.get((S, W, team))
        if not opp: continue   # bye (or traded to a team with a bye)
        x = X[max(0, i - 24):i]; se = SE[max(0, i - 24):i]
        w = 0.5 ** (np.arange(len(x) - 1, -1, -1) / 6.0) * np.where(se == S, 1.0, 0.6)
        m = float((w * x).sum() / w.sum())
        f = FAC[(S, W)].get((opp, last.pos), 1.0)
        lam = ATD_A * m * f + ATD_B; p = 1 - math.exp(-lam)
        nm = last.nm
        sc = SCORED.get((S, W, nm))
        res = '1' if sc is not None and sc >= 1 else '0' if sc is not None or (S, W, nm, team) in PLAYED else 'V'
        rows.append((S, W, nm, team, opp, last.pos, round(m, 4), round(f, 3), round(p, 4), res))

o = pd.DataFrame(rows, columns=['season', 'week', 'nm', 'team', 'opp', 'pos', 'm_td', 'opp_f', 'p', 'res'])
o.to_csv(out, index=False)
print(len(o), 'player-weeks;', o.groupby('season').size().to_dict(), 'results', o.res.value_counts().to_dict(), file=sys.stderr)
pl = o[o.res != 'V']
pl = pl.assign(y=(pl.res == '1').astype(int))
print('calibration (played): mean p %.3f vs hit rate %.3f' % (pl.p.mean(), pl.y.mean()), file=sys.stderr)
pl['bin'] = pd.cut(pl.p, [0, .15, .25, .35, .45, .55, 1])
print(pl.groupby(['season', 'bin'], observed=True).agg(n=('y', 'size'), p=('p', 'mean'), hit=('y', 'mean')).round(3).to_string(), file=sys.stderr)
