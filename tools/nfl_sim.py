"""2026 NFL Playoff Simulator page (nfl-sim.html) from the NFL Team Grades model.

Usage: python3 -I tools/nfl_sim.py GAMES.csv nfl-data nfl-sim.html [N_SIMS]

GAMES.csv = nflverse games file (https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv),
downloaded fresh so finished games count. nfl-data = the folder with grades.csv, hfa.csv, bets.csv, totals.csv.
Run by tools/nfl_auto.py after every NFL grades refresh, like tools/cfp_sim.py is for the CFP Simulator.

Win chances: model margin turned into a win chance as the NFL board does moneylines, P = Phi(margin / 11.1).
This week's games use the weekly model's own number (bets.csv); later weeks use the grade gap plus the home
team's home edge (hfa.csv), nothing at neutral sites. Totals: this week's from totals.csv, later games from the
over/under model's scoring ratings (same update rule as nfl_weekly.py), with no weather, QB or injury terms.
Simulates the rest of the regular season, the tiebreakers and the playoffs N_SIMS times (default 20,000),
plus a "favorites win" bracket run 200,000 times.
"""
import sys, collections, datetime, html
import numpy as np, pandas as pd
from math import erf, sqrt

GPATH, ND, OUT = sys.argv[1:4]
N = int(sys.argv[4]) if len(sys.argv) > 4 else 20000
SIG = 11.1
rng = np.random.default_rng(2026)
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
pwin = lambda m: Phi(m / SIG)
FR = {'STL': 'LA', 'SD': 'LAC', 'OAK': 'LV', 'LAR': 'LA', 'JAC': 'JAX', 'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU', 'SL': 'LA'}
DIV = {'AFC East': ['BUF', 'MIA', 'NE', 'NYJ'], 'AFC North': ['BAL', 'CIN', 'CLE', 'PIT'], 'AFC South': ['HOU', 'IND', 'JAX', 'TEN'],
       'AFC West': ['DEN', 'KC', 'LV', 'LAC'], 'NFC East': ['DAL', 'NYG', 'PHI', 'WAS'], 'NFC North': ['CHI', 'DET', 'GB', 'MIN'],
       'NFC South': ['ATL', 'CAR', 'NO', 'TB'], 'NFC West': ['ARI', 'LA', 'SF', 'SEA']}
NAME = {'ARI': 'Cardinals', 'ATL': 'Falcons', 'BAL': 'Ravens', 'BUF': 'Bills', 'CAR': 'Panthers', 'CHI': 'Bears', 'CIN': 'Bengals', 'CLE': 'Browns',
        'DAL': 'Cowboys', 'DEN': 'Broncos', 'DET': 'Lions', 'GB': 'Packers', 'HOU': 'Texans', 'IND': 'Colts', 'JAX': 'Jaguars', 'KC': 'Chiefs',
        'LA': 'Rams', 'LAC': 'Chargers', 'LV': 'Raiders', 'MIA': 'Dolphins', 'MIN': 'Vikings', 'NE': 'Patriots', 'NO': 'Saints', 'NYG': 'Giants',
        'NYJ': 'Jets', 'PHI': 'Eagles', 'PIT': 'Steelers', 'SEA': 'Seahawks', 'SF': '49ers', 'TB': 'Buccaneers', 'TEN': 'Titans', 'WAS': 'Commanders'}
TEAMS = sorted(NAME); TI = {t: i for i, t in enumerate(TEAMS)}; T = len(TEAMS)
DIVOF = np.array([[d for d, ts in DIV.items() if t in ts][0] for t in TEAMS])
CONF = np.array([d[:3] for d in DIVOF])

# ---- inputs ----
GR = pd.read_csv(f'{ND}/grades.csv').set_index('team').grade.to_dict()
HE = pd.read_csv(f'{ND}/hfa.csv').set_index('team').home_edge.to_dict()
BETS = pd.read_csv(f'{ND}/bets.csv'); TOT = pd.read_csv(f'{ND}/totals.csv')
WMARG = {r.matchup: r.model_home for r in BETS.itertuples()}   # "AWAY @ HOME" -> projected home margin
WTOT = {r.matchup: r.model_total for r in TOT.itertuples()}
g = pd.read_csv(GPATH, low_memory=False)
for c in ('home_team', 'away_team'): g[c] = g[c].replace(FR)
SEASON = int(g.season.max())

def scoring_ratings():   # same rule as nfl_weekly.py: 4% of each miss, 40% back to average each season, league level 1%
    gg = g[g.season >= 2013]; off = collections.defaultdict(float); de = collections.defaultdict(float); mu = 45.; ls = None
    for x in gg.itertuples():
        if x.season != ls:
            for t in list(off): off[t] *= .6; de[t] *= .6
            ls = x.season
        if pd.notna(x.home_score) and pd.notna(x.away_score):
            ph = mu / 2 + off[x.home_team] - de[x.away_team]; pa = mu / 2 + off[x.away_team] - de[x.home_team]
            eh = x.home_score - ph; ea = x.away_score - pa
            off[x.home_team] += .04 * eh; de[x.away_team] -= .04 * eh; off[x.away_team] += .04 * ea; de[x.home_team] -= .04 * ea; mu += .01 * (eh + ea)
    return off, de, mu
OFF, DEF, MU = scoring_ratings()
def proj_total(h, a, key=None):
    if key in WTOT and pd.notna(WTOT[key]): return float(WTOT[key])
    return MU + OFF[h] + OFF[a] - DEF[h] - DEF[a]
def margin(h, a, neutral, key=None):
    if key in WMARG and pd.notna(WMARG[key]): return float(WMARG[key])
    return GR[h] - GR[a] + (0 if neutral else HE.get(h, 1.5))

s = g[(g.season == SEASON) & (g.game_type == 'REG')].sort_values(['week', 'gameday', 'gametime'])
done = s[s.result.notna()]; left = s[s.result.isna()]
GH = np.array([TI[t] for t in s.home_team]); GA = np.array([TI[t] for t in s.away_team]); NG = len(s)
FIXED = np.where(s.result.isna(), np.nan, np.sign(s.result.fillna(0)) * .5 + .5)   # home result: 1 win, .5 tie, 0 loss
LEFTI = np.where(s.result.isna())[0]
LG = []
for r in left.itertuples():
    key = f'{r.away_team} @ {r.home_team}'; neu = r.location == 'Neutral'
    m = margin(r.home_team, r.away_team, neu, key)
    LG.append(dict(week=int(r.week), date=r.gameday, h=r.home_team, a=r.away_team, neutral=neu, m=m, p=pwin(m), tot=proj_total(r.home_team, r.away_team, key)))
P = np.array([x['p'] for x in LG]); CW = int(left.week.min()) if len(left) else 18
SAMED = DIVOF[GH] == DIVOF[GA]; SAMEC = CONF[GH] == CONF[GA]

# ---- tiebreakers ----
class Season:
    def __init__(s_, res):
        s_.res = res; w = np.zeros(T); n = np.zeros(T)
        np.add.at(w, GH, res); np.add.at(w, GA, 1 - res); np.add.at(n, GH, 1); np.add.at(n, GA, 1)
        s_.w = w; s_.n = n; s_.pct = w / n; s_._c = {}
    def rec(s_, t, mask):   # (wins, games) for team t in games where mask
        mh = mask & (GH == t); ma = mask & (GA == t)
        return s_.res[mh].sum() + (1 - s_.res[ma]).sum(), mh.sum() + ma.sum()
    def pct_in(s_, t, mask):
        w, n = s_.rec(t, mask); return w / n if n else None
    def opps(s_, t):
        if ('o', t) not in s_._c: s_._c[('o', t)] = set(GA[GH == t]) | set(GH[GA == t])
        return s_._c[('o', t)]
    def sov(s_, t):
        beat = list(GA[(GH == t) & (s_.res == 1)]) + list(GH[(GA == t) & (s_.res == 0)])
        return s_.w[beat].sum() / s_.n[beat].sum() if beat else 0
    def sos(s_, t):
        op = list(GA[GH == t]) + list(GH[GA == t]); return s_.w[op].sum() / s_.n[op].sum()
    def among(s_, t, S):
        m = (np.isin(GH, S) & np.isin(GA, S)); return s_.pct_in(t, m)

def _best(vals):
    v = [x for x in vals.values() if x is not None]
    if not v or len(v) < len(vals): return None
    mx = max(v); return [t for t, x in vals.items() if abs(x - mx) < 1e-9]

def pick_best(S, se, kind):
    """The team that comes out on top of tied group S. kind: 'div' or 'wc'."""
    S = list(S)
    while len(S) > 1:
        steps = []
        if kind == 'div' or len(S) == 2:
            steps.append(lambda t: se.among(t, S))
        else:   # wild card, 3+: head-to-head only for a sweep
            def sweep(t):
                beat_all = all(se.among(t, [t, u]) == 1 for u in S if u != t)
                lost_all = all(se.among(t, [t, u]) == 0 for u in S if u != t)
                return 1 if beat_all else (0 if lost_all else .5)
            steps.append(sweep)
        if kind == 'div': steps.append(lambda t: se.pct_in(t, SAMED & ((GH == t) | (GA == t))))
        def common(t):
            com = set.intersection(*[se.opps(u) for u in S]) - set(S)
            if kind == 'wc' and len(com) < 4: return 0
            m = np.isin(GH, list(com)) | np.isin(GA, list(com)); return se.pct_in(t, m) or 0
        cf = lambda t: se.pct_in(t, SAMEC & ((GH == t) | (GA == t)))
        steps += [common, cf] if kind == 'div' else [cf, common]
        steps += [se.sov, se.sos]
        new = None
        for f in steps:
            b = _best({t: f(t) for t in S})
            if b is not None and len(b) < len(S): new = b; break
        if new is None: return S[rng.integers(len(S))]   # points-based steps not modeled: coin flip
        S = new   # restart from step 1 with the teams still tied
    return S[0]

def order(group, se, kind):
    out = []; rem = list(group)
    while rem:
        top = max(se.pct[t] for t in rem); tied = [t for t in rem if abs(se.pct[t] - top) < 1e-9]
        b = tied[0] if len(tied) == 1 else pick_best(tied, se, kind)
        out.append(b); rem.remove(b)
    return out

def seed(se):
    seeds = {}
    for cf in ('AFC', 'NFC'):
        divo = {d: order([TI[t] for t in ts], se, 'div') for d, ts in DIV.items() if d.startswith(cf)}
        winners = order([o[0] for o in divo.values()], se, 'wc')
        rest = [t for o in divo.values() for t in o[1:]]; wc = []
        while len(wc) < 3:
            top = max(se.pct[t] for t in rest); tied = [t for t in rest if abs(se.pct[t] - top) < 1e-9]
            if len(tied) > 1:   # only the best team from each division stays in
                tied = [min([t for t in tied if DIVOF[t] == d], key=lambda t: divo[d].index(t)) for d in sorted({DIVOF[t] for t in tied})]
            b = tied[0] if len(tied) == 1 else pick_best(tied, se, 'wc')
            wc.append(b); rest.remove(b)
        seeds[cf] = winners + wc
    return seeds

def pg(h, a, neutral=False): return pwin(GR[TEAMS[h]] - GR[TEAMS[a]] + (0 if neutral else HE.get(TEAMS[h], 1.5)))
def playoffs(seeds, chalk=False, rr=None):
    rr = rr or rng.random
    play = lambda h, a, neu=False: h if ((pg(h, a, neu) >= .5) if chalk else (rr() < pg(h, a, neu))) else a
    reach = collections.defaultdict(set); champs = {}
    for cf, sd in seeds.items():
        rank = {t: i for i, t in enumerate(sd)}
        reach['div'].add(sd[0]); alive = [sd[0]] + [play(sd[i], sd[7 - i]) for i in (1, 2, 3)]
        for t in alive: reach['div'].add(t)
        alive.sort(key=rank.get); d1 = play(alive[0], alive[3]); d2 = play(alive[1], alive[2])
        reach['conf'] |= {d1, d2}; h, a = sorted([d1, d2], key=rank.get); champs[cf] = play(h, a); reach['sb'].add(champs[cf])
    a, n = champs['AFC'], champs['NFC']
    return reach, play(a, n, True)

# ---- regular season + playoffs, N times ----
R = rng.random((N, len(LG))) < P
ST = {k: np.zeros((N, T), bool) for k in ('div', 'po', 'one', 'rdiv', 'conf', 'sb', 'ch')}; WINS = np.zeros((N, T))
for i in range(N):
    res = FIXED.copy(); res[LEFTI] = R[i]; se = Season(res); WINS[i] = se.w
    sd = seed(se)
    for cf, x in sd.items():
        ST['one'][i, x[0]] = 1; ST['po'][i, x] = 1; ST['div'][i, x[:4]] = 1
    reach, ch = playoffs(sd)
    ST['rdiv'][i, list(reach['div'])] = 1; ST['conf'][i, list(reach['conf'])] = 1; ST['sb'][i, list(reach['sb'])] = 1; ST['ch'][i, ch] = 1
M = {k: v.mean(0) for k, v in ST.items()}; PW = WINS.mean(0)
# "favorites win" season and bracket
res = FIXED.copy(); res[LEFTI] = P >= .5; CHALK = seed(Season(res))
NB = 200000; BR = {k: collections.Counter() for k in ('div', 'conf', 'sb', 'ch')}
U = rng.random((NB, 13));
for i in range(NB):
    it = iter(U[i]); reach, ch = playoffs(CHALK, rr=lambda: next(it))
    for k in ('div', 'conf', 'sb'):
        for t in reach[k]: BR[k][t] += 1
    BR['ch'][ch] += 1
REACH_CH, CH_CH = playoffs(CHALK, chalk=True)

# ---- page ----
e = html.escape
lg = lambda t: f'<img class="lg" src="logos/nfl/{t}.png" alt="" loading="lazy">'
nm = lambda t: f'{lg(t)}<span class="nm">{NAME[t]}</span>'
def half(x): return round(x * 2) / 2
def spread(h, a, m):
    if abs(m) < .25: return 'Pick'
    fav = h if m > 0 else a; v = half(abs(m)); v = v if v else .5
    return f'{fav} &minus;{v:g}'
def tot(x): return f'{half(x):g}'
def pc(x, sm=False):
    x *= 100
    if x == 0: return '0%' if not sm else '0.0%'
    if x == 100: return '100%' if not sm else '100.0%'
    if sm: return '&lt;0.1%' if x < .1 else ('&gt;99.9%' if x > 99.9 else f'{x:.1f}%')
    return '&lt;1%' if x < 1 else ('&gt;99%' if x > 99 else f'{x:.0f}%')
def rec(t):
    w = l = ti = 0
    for r in done.itertuples():
        if t not in (r.home_team, r.away_team): continue
        if r.result == 0: ti += 1
        elif (r.result > 0) == (r.home_team == t): w += 1
        else: l += 1
    return f'{w}-{l}' + (f'-{ti}' if ti else '')
REC = {t: rec(t) for t in TEAMS}
def bar(v, txt): return f'<span class="bar" style="--v:{min(100, v * 100):.1f}"></span>{txt}'

def gm(label, h, a, sh, sa, neutral=False, bye=False):
    if bye: return f'<div class="gm bye"><div class="gl">Bye</div><div class="tm w"><span class="sd">1</span>{lg(TEAMS[h])}<span class="nm">{NAME[TEAMS[h]]}</span><span class="pc">bye</span></div></div>'
    p = pg(h, a, neutral); H, A = TEAMS[h], TEAMS[a]; m = GR[H] - GR[A] + (0 if neutral else HE.get(H, 1.5))
    row = lambda t, sdn, q, w: f'<div class="tm{" w" if w else ""}"><span class="sd">{sdn}</span>{lg(t)}<span class="nm">{NAME[t]}</span><span class="pc">{q * 100:.0f}%</span></div>'
    return (f'<div class="gm"><div class="gl">{label}</div>{row(H, sh, p, p >= .5)}{row(A, sa, 1 - p, p < .5)}'
            f'<div class="ln">{spread(H, A, m)} · O/U {tot(proj_total(H, A))}</div></div>')

def conf_bracket(cf):
    sd = CHALK[cf]; rank = {t: i for i, t in enumerate(sd)}; sn = lambda t: rank[t] + 1
    c1 = [gm('', sd[0], None, 1, 0, bye=True)]; alive = [sd[0]]
    for i in (1, 2, 3):
        h, a = sd[i], sd[7 - i]; c1.append(gm(f'Wild card · at {NAME[TEAMS[h]]}', h, a, i + 1, 8 - i)); alive.append(h if pg(h, a) >= .5 else a)
    alive.sort(key=rank.get); c2 = []; nxt = []
    for h, a in ((alive[0], alive[3]), (alive[1], alive[2])):
        c2.append(gm(f'Divisional · at {NAME[TEAMS[h]]}', h, a, sn(h), sn(a))); nxt.append(h if pg(h, a) >= .5 else a)
    h, a = sorted(nxt, key=rank.get)
    c3 = [gm(f'{cf} Championship · at {NAME[TEAMS[h]]}', h, a, sn(h), sn(a))]
    win = h if pg(h, a) >= .5 else a
    return (f'<div class="conf"><div class="ch">{cf}</div><div class="bk"><div class="col">{"".join(c1)}</div><div class="col">{"".join(c2)}</div>'
            f'<div class="col">{"".join(c3)}</div></div></div>'), win, sn(win)

ba, wa, sa = conf_bracket('AFC'); bn, wn, sn_ = conf_bracket('NFC')
def roman(x):
    out = ''
    for v, r in ((50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while x >= v: out += r; x -= v
    return out
sb = gm(f'Super Bowl {roman(SEASON - 1965)} · neutral site', wa, wn, sa, sn_, neutral=True)
champ = wa if pg(wa, wn, True) >= .5 else wn
bracket = (f'<div class="bkwrap">{ba}{bn}<div class="sbx">{sb}<div class="champ">Projected champion<br><b>{NAME[TEAMS[champ]]}</b> · wins it all '
           f'{100 * BR["ch"][champ] / NB:.1f}%</div></div></div>')

rows = []
for cf in ('AFC', 'NFC'):
    for i, t in enumerate(CHALK[cf]):
        d = 'bye' if i == 0 else f'{100 * BR["div"][t] / NB:.1f}%'
        rows.append(f'<tr><td>{cf}</td><td class="n">{i + 1}</td><td>{nm(TEAMS[t])}</td><td class="n">{GR[TEAMS[t]]:.1f}</td>'
                    + ''.join(f'<td class="n">{bar(v, txt)}</td>' for v, txt in ((BR['div'][t] / NB if i else 1, d),
                      (BR['conf'][t] / NB, f'{100 * BR["conf"][t] / NB:.1f}%'), (BR['sb'][t] / NB, f'{100 * BR["sb"][t] / NB:.1f}%'),
                      (BR['ch'][t] / NB, f'{100 * BR["ch"][t] / NB:.1f}%'))) + '</tr>')
run_tbl = ('<div class="tw"><table><thead><tr><th>Conf.</th><th class="n">Seed</th><th>Team</th><th class="n">Grade</th><th class="n">Divisional</th>'
           '<th class="n">Conf. title game</th><th class="n">Super Bowl</th><th class="n">Champion</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')

def full(cf):
    ts = sorted([i for i in range(T) if CONF[i] == cf], key=lambda i: (-M['po'][i], -M['ch'][i], -PW[i]))
    r = ''.join(f'<tr><td>{nm(TEAMS[i])}</td><td class="n">{REC[TEAMS[i]]}</td><td class="n">{PW[i]:.1f}</td><td class="n">{GR[TEAMS[i]]:.1f}</td>'
                f'<td class="n">{pc(M["div"][i])}</td><td class="n">{bar(M["po"][i], pc(M["po"][i], True))}</td><td class="n">{pc(M["one"][i])}</td>'
                f'<td class="n">{pc(M["rdiv"][i], True)}</td><td class="n">{pc(M["conf"][i], True)}</td><td class="n">{pc(M["sb"][i], True)}</td>'
                f'<td class="n b">{pc(M["ch"][i], True)}</td></tr>' for i in ts)
    return (f'<section><h2>Full simulation: {cf}</h2><div class="tw"><table><thead><tr><th>Team</th><th class="n">Record</th><th class="n">Proj. W</th>'
            '<th class="n">Grade</th><th class="n">Win div.</th><th class="n">Make playoffs</th><th class="n">No. 1 seed</th><th class="n">Divisional</th>'
            '<th class="n">Conf. game</th><th class="n">Super Bowl</th><th class="n">Champion</th></tr></thead><tbody>' + r + '</tbody></table></div>')

divs = ''
for d, ts in DIV.items():
    ii = sorted([TI[t] for t in ts], key=lambda i: (-M['div'][i], -PW[i]))
    divs += (f'<div class="tw"><table><thead><tr><th>{d}</th><th class="n">Now</th><th class="n">Proj. W</th><th class="n">Win div.</th></tr></thead><tbody>'
             + ''.join(f'<tr><td>{nm(TEAMS[i])}</td><td class="n">{REC[TEAMS[i]]}</td><td class="n">{PW[i]:.1f}</td><td class="n b">{pc(M["div"][i])}</td></tr>' for i in ii)
             + '</tbody></table></div>')

mx = lambda x: f'<span class="mx">{lg(x["a"])}{x["a"]} <span class="at">{"vs" if x["neutral"] else "at"}</span> {lg(x["h"])}{x["h"]}</span>'
fmtd = lambda d: datetime.date.fromisoformat(d).strftime('%a %b ') + str(datetime.date.fromisoformat(d).day)
wk = [x for x in LG if x['week'] == CW]
picks = ''.join(f'<tr><td>{fmtd(x["date"])}</td><td>{mx(x)}</td><td><b>{NAME[x["h"] if x["p"] >= .5 else x["a"]]}</b></td>'
                f'<td class="n">{max(x["p"], 1 - x["p"]) * 100:.0f}%</td><td class="n">{spread(x["h"], x["a"], x["m"])}</td><td class="n">{tot(x["tot"])}</td></tr>' for x in wk)
# biggest games: how much each team's playoff chance moves between a home win and an away win
PO = ST['po'].astype(float); big = []
for j, x in enumerate(LG):
    hw = R[:, j]; nh = hw.sum()
    if nh < 300 or N - nh < 300: continue
    sw = np.abs(PO[hw].mean(0) - PO[~hw].mean(0)) * 100
    top = np.argsort(-sw)[:2]; big.append((sw.sum(), x, top, sw))
big.sort(key=lambda b: -b[0])
bigr = ''.join(f'<tr><td class="n">{x["week"]}</td><td>{mx(x)}</td><td class="n">{x["p"] * 100:.0f}%</td><td class="n">{spread(x["h"], x["a"], x["m"])}</td>'
               f'<td class="n">{tot(x["tot"])}</td><td>{"; ".join(f"{NAME[TEAMS[t]]} {sw[t]:.0f} pts" for t in top)}</td></tr>' for _, x, top, sw in big[:12])

from zoneinfo import ZoneInfo
now = datetime.datetime.now(ZoneInfo('America/New_York'))
upd = now.strftime('%b. ') + str(now.day)
page = open(__file__.replace('nfl_sim.py', 'nfl_sim_template.html')).read()
for k, v in {'{{WEEK}}': str(CW), '{{UPDATED}}': upd, '{{LEFT}}': str(len(LG)), '{{BRACKET}}': bracket, '{{RUNTABLE}}': run_tbl, '{{NB}}': f'{NB:,}',
             '{{AFC}}': full('AFC'), '{{NFC}}': full('NFC'), '{{N}}': f'{N:,}', '{{DIVS}}': divs, '{{PICKS}}': picks, '{{BIG}}': bigr, '{{SEASON}}': str(SEASON)}.items():
    page = page.replace(k, v)
open(OUT, 'w').write(page)
print(f'nfl-sim: week {CW}, {len(LG)} games left, {N} sims; champion favorite {NAME[TEAMS[int(M["ch"].argmax())]]} {M["ch"].max() * 100:.1f}%')
