"""Build nfl_matchups.json (the info-only "Matchup" panel in the Line Shop) from this season's
nflverse play-by-play and this week's games in nfl_model.json. Same file shape as cfb_matchups.json.

Usage: python3 tools/build_nfl_matchups.py WORKDIR nfl_model.json nfl_matchups.json
       python3 tools/build_nfl_matchups.py WORKDIR --backtest      (2021 on, prints the check against closing lines)

Every unit is rated opponent-adjusted (offense and defense effects fit together, shrunk toward average),
then each game is shown unit vs unit. Passing = every dropback (passes, sacks, scrambles).
Explosive = a run of 10+ yards or a pass of 20+. Run stuff = a run for no gain or a loss. Sacks = sack yards lost per dropback.
"""
import json, sys, os, subprocess, datetime
import numpy as np, pandas as pd

MET = {'rush_epa': True, 'pass_epa': True, 'sr_rush': True, 'sr_pass': True, 'pass_rate': None,
       'plays': None, 'expl': True, 'stuff': False, 'sack': False}
FR = {'STL': 'LA', 'SD': 'LAC', 'OAK': 'LV', 'LAR': 'LA', 'JAC': 'JAX'}
COLS = ['game_id', 'season', 'week', 'posteam', 'defteam', 'home_team', 'rush', 'pass', 'epa', 'yards_gained', 'sack', 'success', 'play_type', 'location']
URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_%d.parquet'


def pbp(wd, y, refresh):
    f = os.path.join(wd, f'pbp_{y}.parquet')
    if refresh or not os.path.exists(f):
        if subprocess.run(['curl', '-sSfL', '-o', f, URL % y]).returncode: raise SystemExit(f'download failed: play-by-play {y}')
    return pd.read_parquet(f, columns=COLS)


def team_games(d):
    """One row per offense per game."""
    d = d[d.play_type.isin(['pass', 'run']) & d.epa.notna() & d.posteam.notna()].copy()
    for c in ('posteam', 'defteam', 'home_team'): d[c] = d[c].replace(FR)
    p = d['pass'] == 1; r = ~p
    d['re'] = d.epa.where(r); d['pe'] = d.epa.where(p); d['rs'] = d.success.where(r); d['ps'] = d.success.where(p)
    d['ex'] = ((r & (d.yards_gained >= 10)) | (p & (d.yards_gained >= 20))).astype(float)
    d['st'] = (d.yards_gained <= 0).where(r).astype(float); d['sy'] = np.where(d.sack == 1, -d.yards_gained, 0.); d['p'] = p.astype(float)
    g = d.groupby(['season', 'week', 'game_id', 'posteam', 'defteam', 'home_team', 'location'], as_index=False).agg(
        rush_epa=('re', 'mean'), pass_epa=('pe', 'mean'), sr_rush=('rs', 'mean'), sr_pass=('ps', 'mean'), pass_rate=('p', 'mean'),
        plays=('p', 'size'), expl=('ex', 'mean'), stuff=('st', 'mean'), sy=('sy', 'sum'), db=('p', 'sum'))
    g['sack'] = g.sy / g.db.clip(lower=1)
    g['ha'] = np.where(g.location == 'Neutral', 0, np.where(g.posteam == g.home_team, 1, -1))
    return g.dropna(subset=list(MET))


def rate(L, shrink=4.0):
    t = sorted(set(L.posteam) | set(L.defteam)); ix = {k: i for i, k in enumerate(t)}; n = len(t)
    A = np.zeros((len(L), 2 * n + 2)); r = np.arange(len(L))
    A[r, [ix[k] for k in L.posteam]] = 1; A[r, [n + ix[k] for k in L.defteam]] = 1; A[:, 2 * n] = 1; A[:, 2 * n + 1] = L.ha.values
    AtA = A.T @ A + np.diag(np.r_[np.full(2 * n, shrink), 1e-6, 1e-6]); R = {}
    for m in MET:
        b = np.linalg.solve(AtA, A.T @ L[m].values)
        R[m] = dict(o=dict(zip(t, b[:n])), d=dict(zip(t, b[n:2 * n])), mu=float(b[2 * n]))
    return R, t


def proj(R, m, o, d):
    return R[m]['o'].get(o, 0.) + R[m]['d'].get(d, 0.) + R[m]['mu']


def backtest(wd):
    """Before each game (week 5 on), rate every unit from that season's earlier games, then ask whether the matchup
    edge says anything the closing spread and total don't already say."""
    gm = pd.read_csv('https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv') if not os.path.exists(os.path.join(wd, 'games.csv')) else pd.read_csv(os.path.join(wd, 'games.csv'))
    for c in ('home_team', 'away_team'): gm[c] = gm[c].replace(FR)
    rows = []
    for y in range(2021, int(gm.season.max()) + 1):
        G = team_games(pbp(wd, y, False)); gy = gm[(gm.season == y) & gm.result.notna() & gm.spread_line.notna() & gm.total_line.notna()]
        for w in sorted(gy.week.unique()):
            if w < 5: continue
            L = G[G.week < w]
            if L.empty: continue
            R, _ = rate(L)
            for x in gy[gy.week == w].itertuples():
                h, a = x.home_team, x.away_team
                e = lambda m, o, d: proj(R, m, o, d) - R[m]['mu']
                # expected points added per play for each offense in this matchup, mixed by its projected pass rate
                def off(o, d):
                    pr = proj(R, 'pass_rate', o, d); return pr * proj(R, 'pass_epa', o, d) + (1 - pr) * proj(R, 'rush_epa', o, d)
                oh, oa = off(h, a), off(a, h)
                rows.append(dict(season=y, week=w, net=oh - oa, tot=oh + oa, pace=proj(R, 'plays', h, a) + proj(R, 'plays', a, h),
                                 expl=e('expl', h, a) - e('expl', a, h), ats=x.result - x.spread_line, ou=x.total - x.total_line,
                                 hs=x.home_score - (x.total_line + x.spread_line) / 2, as_=x.away_score - (x.total_line - x.spread_line) / 2, oh=oh, oa=oa))
    B = pd.DataFrame(rows); out = {}
    def rec(sig, res, q):
        cut = sig.abs().quantile(q); m = sig.abs() >= cut; v = np.sign(sig[m]) * res[m]; w, l = int((v > 0).sum()), int((v < 0).sum()); return f'{w}-{l} ({100 * w / max(w + l, 1):.1f}%)'
    c = lambda a, b: round(float(np.corrcoef(a, b)[0, 1]), 3)
    print('games', len(B), 'seasons', B.season.min(), '-', B.season.max())
    print('spread: matchup edge vs result against the closing spread: corr', c(B.net, B.ats), '| all', rec(B.net, B.ats, 0), '| biggest third', rec(B.net, B.ats, 2 / 3), '| biggest tenth', rec(B.net, B.ats, .9))
    ts = (B.tot - B.tot.mean()) / B.tot.std() + (B.pace - B.pace.mean()) / B.pace.std()
    print('total: offense + pace edge vs result against the closing total: corr', c(ts, B.ou), '| all', rec(ts, B.ou, 0), '| biggest third', rec(ts, B.ou, 2 / 3), '| biggest tenth', rec(ts, B.ou, .9))
    tt_s = pd.concat([B.oh - B.oh.mean(), B.oa - B.oa.mean()]); tt_r = pd.concat([B.hs, B.as_])
    print('team total: offense edge vs result against the implied team total: corr', c(tt_s, tt_r), '| all', rec(tt_s, tt_r, 0), '| biggest third', rec(tt_s, tt_r, 2 / 3))
    r3 = B[B.season >= B.season.max() - 3]
    print('spread around closing lines, last 4 seasons: margin %.1f, total %.1f, team total %.1f' % (r3.ats.std(), r3.ou.std(), pd.concat([r3.hs, r3.as_]).std()))


def main():
    wd = sys.argv[1]; os.makedirs(wd, exist_ok=True)
    if '--backtest' in sys.argv: return backtest(wd)
    model = json.load(open(sys.argv[2])); out = sys.argv[3]
    today = datetime.date.today(); Y = today.year if today.month >= 8 else today.year - 1
    G = team_games(pbp(wd, Y, True)); G = G[G.season == Y]
    R, t = rate(G)
    def ranks(m, side):
        v = R[m][side]; good = MET[m]
        key = (lambda k: -v[k]) if (good is True) == (side == 'o') else (lambda k: v[k])
        return {k: i + 1 for i, k in enumerate(sorted(t, key=key))}
    RK = {(m, sd): ranks(m, sd) for m in MET if MET[m] is not None for sd in ('o', 'd')}
    rnd = lambda x, k=3: round(float(x), k)
    def unit(o, d):
        u = {}
        for m, good in MET.items():
            e = dict(proj=rnd(proj(R, m, o, d)), avg=rnd(R[m]['mu']), own=rnd(R[m]['o'][o] + R[m]['mu']))
            if good is not None: e['o_rank'] = RK[(m, 'o')][o]; e['d_rank'] = RK[(m, 'd')][d]
            u[m] = e
        return u
    games = [dict(away=x['away'], home=x['home'], away_off=unit(x['away'], x['home']), home_off=unit(x['home'], x['away']))
             for x in model.get('games', []) if x['away'] in t and x['home'] in t]
    json.dump({'season': Y, 'through_week': int(G.week.max()), 'msd': {m: rnd(np.std(list(R[m]['o'].values()))) for m in MET},
               'updated': today.isoformat(), 'fbs_teams': len(t), 'pool': 'NFL',
               # spread of results around closing lines, 2023-26: margin, game total, team total
               'sd': {'margin': SD[0], 'total': SD[1], 'team_total': SD[2]},
               'note': NOTE, 'games': games}, open(out, 'w'), separators=(',', ':'))
    print(len(games), 'games written of', len(model.get('games', [])), '| through week', int(G.week.max()))


SD = (12.3, 13.0, 8.9)      # from --backtest: games from week 5 on, last 4 seasons
NOTE = 'Information only: these matchup edges did not beat closing spreads, totals or team totals in a 2021-26 backtest.'
if __name__ == '__main__':
    main()
