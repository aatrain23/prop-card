#!/usr/bin/env python3
"""Tackles + assists backtest data: one row per defender-game 2021-2026 (REG), with pregame projections for every variant.

usage: python3 -I build_tkl.py DATADIR OUT.parquet
Universe: every defender with defensive snaps in the snap counts, plus any stats row (tackles fill 0 when he played but has no stats row).
All features use only games before the one being projected (and the injury report for that week, known pregame).
"""
import sys, numpy as np, pandas as pd

D, OUT = sys.argv[1:3]
YRS = range(2021, 2027)

def ew(vals, seas, cur, hl, lw, n=24):
    """exponentially weighted mean of earlier games (newest last), last-season weight lw"""
    v = vals[-n:]; s = seas[-n:]
    age = np.arange(len(v) - 1, -1, -1)
    w = 0.5 ** (age / hl) * np.where(s == cur, 1.0, lw)
    return (w * v).sum() / w.sum(), w

# ---- stats
st = pd.concat([pd.read_csv(f'{D}/stats_{y}.csv', low_memory=False) for y in YRS], ignore_index=True)
st = st[st.season_type == 'REG'].copy()
for c in ['def_tackles_solo', 'def_tackle_assists', 'def_tackles_with_assist', 'attempts', 'carries', 'sacks_suffered']:
    st[c] = pd.to_numeric(st[c], errors='coerce').fillna(0)
st['tkl'] = st.def_tackles_solo + st.def_tackle_assists + st.def_tackles_with_assist   # matches how books graded 99% of expert picks
st['tkl_live'] = st.tkl
st['pos'] = st.position_group.fillna(st.position)
# team offensive plays per game (pass att + sacks + carries) -> opponent volume
tp = st.groupby(['season', 'week', 'team'])[['attempts', 'sacks_suffered', 'carries']].sum().reset_index()
tp['plays'] = tp.attempts + tp.sacks_suffered + tp.carries
tp['runs'] = tp.carries

# ---- snaps (pfr id -> gsis)
pl = pd.read_csv(f'{D}/players.csv', low_memory=False)[['gsis_id', 'pfr_id', 'position_group']].dropna(subset=['gsis_id'])
pmap = dict(zip(pl.pfr_id, pl.gsis_id))
sn = pd.concat([pd.read_csv(f'{D}/snaps_{y}.csv') for y in YRS], ignore_index=True)
sn = sn[sn.game_type == 'REG'].copy()
sn['player_id'] = sn.pfr_player_id.map(pmap)
sn = sn.dropna(subset=['player_id'])
sn = sn[sn.defense_snaps > 0][['season', 'week', 'team', 'opponent', 'player_id', 'player', 'position', 'defense_snaps', 'defense_pct']]
sn = sn.drop_duplicates(['season', 'week', 'player_id'])
team_def = sn.groupby(['season', 'week', 'team']).defense_snaps.max().rename('team_snaps').reset_index()  # ~ max = 100% snaps

DEFPOS = {'LB', 'DB', 'DL'}
sd = st[st.pos.isin(DEFPOS)][['season', 'week', 'team', 'opponent_team', 'player_id', 'player_name', 'player_display_name', 'pos', 'tkl', 'tkl_live']]
df = sn.merge(sd, on=['season', 'week', 'player_id'], how='outer', suffixes=('', '_st'))
df['team'] = df.team.fillna(df.team_st); df['opp'] = df.opponent_team.fillna(df.opponent)
df['instats'] = df.tkl.notna()
df[['tkl', 'tkl_live']] = df[['tkl', 'tkl_live']].fillna(0)
# position group: stats, else players file, else snap position
pg = dict(zip(pl.gsis_id, pl.position_group))
SNAPPOS = {'LB': 'LB', 'ILB': 'LB', 'OLB': 'LB', 'MLB': 'LB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB',
           'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL'}
df['pos'] = df.pos.fillna(df.player_id.map(pg)).fillna(df.position.map(SNAPPOS))
df = df[df.pos.isin(DEFPOS)].copy()
# name key like the backtest's (nflverse short name "B.Okereke"); fill from other seasons
nmap = sd.dropna(subset=['player_name']).groupby('player_id').player_name.last()
df['player_name'] = df.player_name.fillna(df.player_id.map(nmap))
df = df.merge(team_def, on=['season', 'week', 'team'], how='left')
df['t'] = df.season * 100 + df.week
df = df.sort_values(['player_id', 't']).reset_index(drop=True)

# ---- games: spread, home team (stat crew), for each team-game
g = pd.read_csv(f'{D}/games.csv'); g = g[(g.game_type == 'REG') & g.season.isin(YRS)]
rows = []
for r in g.itertuples():
    rows.append((r.season, r.week, r.home_team, r.home_team, r.spread_line, r.total_line, 1))
    rows.append((r.season, r.week, r.away_team, r.home_team, -r.spread_line, r.total_line, 0))
G = pd.DataFrame(rows, columns=['season', 'week', 'team', 'venue', 'team_spread', 'total_line', 'home'])
df = df.merge(G, on=['season', 'week', 'team'], how='left')

# ---- per-player walk-forward projections
V = {k: np.full(len(df), np.nan) for k in ['base_live', 'base_bk', 'ew_all', 'rate', 'pct_proj', 'snaps_proj', 'gb', 'gb_cur',
                                             'ew_hl3', 'ew_hl4', 'ew_hl8', 'ew_lw4', 'ew_lw8', 'ew_n12', 'last_pct', 'rate_hl10']}
for pid, gg in df.groupby('player_id', sort=False):
    idx = gg.index.values; seas = gg.season.values
    tk = gg.tkl.values.astype(float); tl = gg.tkl_live.values.astype(float); ins = gg.instats.values
    ds = gg.defense_snaps.fillna(0).values.astype(float); dp = gg.defense_pct.fillna(np.nan).values.astype(float)
    for i in range(1, len(idx)):
        cur = seas[i]
        # live model: stats rows only, tkl incl. with_assist
        m = ins[:i]
        if m.sum():
            V['base_live'][idx[i]] = ew(tl[:i][m], seas[:i][m], cur, 6, .6)[0]
            V['base_bk'][idx[i]] = ew(tk[:i][m], seas[:i][m], cur, 6, .6)[0]
            V['gb'][idx[i]] = m.sum()
        V['gb_cur'][idx[i]] = (seas[:i] == cur).sum()
        V['ew_all'][idx[i]], w = ew(tk[:i], seas[:i], cur, 6, .6)
        for hl in (3, 4, 8): V[f'ew_hl{hl}'][idx[i]] = ew(tk[:i], seas[:i], cur, hl, .6)[0]
        V['ew_lw4'][idx[i]] = ew(tk[:i], seas[:i], cur, 6, .4)[0]
        V['ew_lw8'][idx[i]] = ew(tk[:i], seas[:i], cur, 6, .8)[0]
        V['ew_n12'][idx[i]] = ew(tk[:i], seas[:i], cur, 6, .6, n=12)[0]
        # snap model: tackles per snap (weighted ratio, long memory) x expected snap share (short memory)
        for key, hl in (('rate', 6), ('rate_hl10', 10)):
            has = ds[:i] > 0                       # only games with snap data (a missing snap row is not 0 snaps)
            if not has.any(): continue
            v = tk[:i][has][-24:]; s_ = ds[:i][has][-24:]; ss = seas[:i][has][-24:]
            age = np.arange(len(v) - 1, -1, -1); w = 0.5 ** (age / hl) * np.where(ss == cur, 1.0, .6)
            V[key][idx[i]] = (w * v).sum() / max((w * s_).sum(), 1)
        p = dp[:i]; ok = ~np.isnan(p)
        if ok.sum():
            V['pct_proj'][idx[i]] = ew(p[ok], seas[:i][ok], cur, 2, .6, n=8)[0]
            V['last_pct'][idx[i]] = p[ok][-1]
        has = ds[:i] > 0
        if has.any(): V['snaps_proj'][idx[i]] = ew(ds[:i][has], seas[:i][has], cur, 2, .6, n=8)[0]
for k, v in V.items(): df[k] = v

# ---- team context (pregame): expected team defensive snaps = opponent plays per game so far (shrunk to league), team's own snaps
tp = tp.sort_values(['team', 'season', 'week'])
def team_ew(frame, col, hl=4):
    out = []
    for t, x in frame.groupby('team'):
        x = x.sort_values(['season', 'week']); vals = x[col].values; ss = x.season.values
        for i in range(len(x)):
            if i == 0: out.append(np.nan); continue
            out.append(ew(vals[:i], ss[:i], ss[i], hl, .5, n=16)[0])
    return pd.Series(out, index=frame.sort_values(['team', 'season', 'week']).index)
tp['plays_ew'] = team_ew(tp, 'plays'); tp['run_share'] = tp.runs / tp.plays; tp['run_ew'] = team_ew(tp, 'run_share')
lg = tp.groupby('season').plays.mean()
opp = tp[['season', 'week', 'team', 'plays_ew', 'run_ew']].rename(columns={'team': 'opp', 'plays_ew': 'opp_plays_ew', 'run_ew': 'opp_run_ew'})
df = df.merge(opp, on=['season', 'week', 'opp'], how='left')
df['lg_plays'] = df.season.map(lg)
# the defense's own snaps per game so far (pace of their games) for the snap model
td = team_def.sort_values(['team', 'season', 'week']).copy(); td['own_snaps_ew'] = team_ew(td, 'team_snaps')
df = df.merge(td[['season', 'week', 'team', 'own_snaps_ew']], on=['season', 'week', 'team'], how='left')

# ---- stat crew: tackles + assists recorded per game at each home stadium, prior seasons, vs league
ga = df.groupby(['season', 'week', 'venue']).tkl.sum().reset_index()
vf = {}
for S in YRS:
    pr = ga[(ga.season < S) & (ga.season >= S - 3)]
    if pr.empty: continue
    lgm = pr.tkl.mean(); per = pr.groupby('venue').tkl.agg(['mean', 'size'])
    for v, r in per.iterrows():
        vf[(S, v)] = (r['mean'] / lgm * r['size'] + 8) / (r['size'] + 8)   # shrink: 8 games of league average
df['venue_f'] = [vf.get((s, v), 1.0) for s, v in zip(df.season, df.venue)]
# player's usual venue factor (his last 16 games) so the adjustment is relative to what's already in his average
df['venue_hist'] = df.groupby('player_id').venue_f.transform(lambda x: x.shift(1).rolling(16, min_periods=1).mean()).fillna(1.0)

# ---- teammate injuries: regular starters ruled Out/Doubtful this week who played >= 50% of snaps in the team's last game
inj = pd.concat([pd.read_csv(f'{D}/inj_{y}.csv') for y in YRS], ignore_index=True)
inj = inj[(inj.season_type == 'REG') & inj.report_status.isin(['Out', 'Doubtful'])][['season', 'week', 'team', 'gsis_id']].drop_duplicates()
inj = inj.rename(columns={'gsis_id': 'player_id'})
# each player's projection carried to the week he's out: his last row's ew_all and pct in the prior game
last = df[['season', 'week', 'team', 'player_id', 'pos', 'defense_pct', 'ew_all', 'tkl']].copy()
last['key_next'] = list(zip(last.season, last.team))
out_rows = []
tw = df[['season', 'week', 'team']].drop_duplicates().sort_values(['team', 'season', 'week'])
prev_week = {}
for t, x in tw.groupby('team'):
    x = x.values.tolist()
    for a, b in zip(x[:-1], x[1:]):
        if a[0] == b[0]: prev_week[(b[0], b[1], t)] = a[1]
lk = last.set_index(['season', 'week', 'team', 'player_id'])
for r in inj.itertuples():
    pw = prev_week.get((r.season, r.week, r.team))
    if pw is None: continue
    k = (r.season, pw, r.team, r.player_id)
    if k not in lk.index: continue
    q = lk.loc[k]
    if isinstance(q, pd.DataFrame): q = q.iloc[0]
    if q.defense_pct >= 0.5:
        # his expected tackles = his avg tackles going into last week, updated with last week's game
        out_rows.append((r.season, r.week, r.team, q.pos, float(np.nanmean([q.ew_all, q.tkl]) if not np.isnan(q.ew_all) else q.tkl)))
O = pd.DataFrame(out_rows, columns=['season', 'week', 'team', 'pos', 'miss']).groupby(['season', 'week', 'team', 'pos']).miss.sum().rename('miss_tkl').reset_index()
df = df.merge(O, on=['season', 'week', 'team', 'pos'], how='left'); df['miss_tkl'] = df.miss_tkl.fillna(0)
# is this player himself reported Out (he then won't play; rows exist only if he did play, so ignore)
df.to_parquet(OUT, index=False)
print(len(df), 'rows;', df.season.value_counts().sort_index().to_dict())
