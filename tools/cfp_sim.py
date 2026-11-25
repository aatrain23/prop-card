"""2026 CFP Simulator page (cfp-sim.html) from the CFB model's team grades.

Usage: python3 -I tools/cfp_sim.py cfb-data/grades.csv SCHEDULE.csv tools/cfp_state.json cfp-sim.html

SCHEDULE.csv = this season's cfbfastR schedule (https://raw.githubusercontent.com/sportsdataverse/
cfbfastR-data/main/schedules/csv/cfb_schedules_<season>.csv), downloaded fresh so finished games count.
Simulates the rest of the regular season, the conference title games, the committee's picks and the
12-team playoff 20,000 times, plus a "favorites win" bracket run 200,000 times.

Win chances: grade gap (+ home edge for home games) as the model's spread, results spread with an
SD of 15.5 points (about how the model's misses land). Title-game spots not yet set: conference record,
then head-to-head, then grade (an approximation of real tiebreakers). Committee: the latest CFP ranking
(tools/cfp_state.json); a loss drops a ranked team ~5 spots, a title-game loss ~2.5, a title-game win
lifts it ~2, plus noise. Field: 4 power champions + top Group of 6 champion + next 7; top 4 get byes.
Once tools/cfp_state.json has a bracket, only the playoff is simulated.
"""
import sys, json, collections, datetime, html
import numpy as np, pandas as pd
from math import erf, sqrt

GPATH, SPATH, STATE, OUT = sys.argv[1:5]
TPL = __file__.replace('cfp_sim.py', 'cfp_sim_template.html')
g = pd.read_csv(GPATH).set_index('team'); GR = g.grade.to_dict(); HE = g.home_edge.to_dict(); SD = 15.5
st = json.load(open(STATE))
gr = lambda t: GR.get(t, 35.0)
def ph(h, a, neutral):
    d = gr(h) - gr(a) + (0 if neutral else HE.get(h, 2.5)); return 0.5 * (1 + erf(d / SD / sqrt(2)))
s = pd.read_csv(SPATH, low_memory=False)
FBS = set(s[s.home_division == 'fbs'].home_team) | set(s[s.away_division == 'fbs'].away_team)
conf = {}
for r in s.itertuples():
    if r.home_division == 'fbs': conf[r.home_team] = r.home_conference
    if r.away_division == 'fbs': conf[r.away_team] = r.away_conference
isccg = s.notes.fillna('').str.contains('Championship') & (s.season_type == 'regular')
reg = s[(s.season_type == 'regular') & ~isccg & (s.home_team != 'Army') | ((s.season_type == 'regular') & ~isccg & (s.week < 15))]
reg = reg[~reg.index.duplicated()]
past = reg[reg.completed == True]; left = reg[reg.completed != True]
W = collections.Counter(); L = collections.Counter(); CW = collections.Counter(); CL = collections.Counter(); H2H = {}
def add(w, l, ic, cf, W, L, CW, CL, H):
    W[w] += 1; L[l] += 1
    if ic: CW[(cf, w)] += 1; CL[(cf, l)] += 1; H[(w, l)] = 1
for r in past.itertuples():
    w, l = (r.home_team, r.away_team) if r.home_points > r.away_points else (r.away_team, r.home_team)
    add(w, l, bool(r.conference_game) and r.home_conference == r.away_conference, r.home_conference, W, L, CW, CL, H2H)
games = [(r.home_team, r.away_team, bool(r.neutral_site), bool(r.conference_game) and r.home_conference == r.away_conference, r.home_conference,
          ph(r.home_team, r.away_team, bool(r.neutral_site))) for r in left.itertuples() if r.home_team in FBS or r.away_team in FBS]
CCG = dict(st.get('ccg', {}))
for r in s[isccg].itertuples():
    if r.home_division == 'fbs' and r.away_division == 'fbs': CCG[r.home_conference if r.home_conference == r.away_conference else conf[r.home_team]] = [r.home_team, r.away_team]
ccg_done = {}
for r in s[isccg & (s.completed == True)].itertuples():
    ccg_done[conf[r.home_team]] = r.home_team if r.home_points > r.away_points else r.away_team
RANK = st['ranking']; RK = {t: i + 1 for i, t in enumerate(RANK)}
for i, t in enumerate(sorted([t for t in FBS if t not in RK], key=lambda t: -gr(t))): RK[t] = 26 + i * 0.5
P4 = ['SEC', 'Big Ten', 'Big 12', 'ACC']; G6 = ['American Athletic', 'Conference USA', 'Mid-American', 'Mountain West', 'Pac-12', 'Sun Belt']
CONFS = [c for c in P4 + G6 if any(conf.get(t) == c for t in FBS)]
def pick2(cf, cw, cl, h2h):
    pct = lambda t: cw[(cf, t)] / max(1, cw[(cf, t)] + cl[(cf, t)])
    T = sorted([t for t in FBS if conf.get(t) == cf], key=lambda t: (-pct(t), -gr(t)))
    tied = [t for t in T[1:] if pct(t) == pct(T[1])]
    if len(tied) == 2 and h2h.get((tied[1], tied[0])): tied = tied[::-1]
    return T[0], tied[0]
def season(rng, chalk=False):
    w, l, cw, cl, h2h, res = W.copy(), L.copy(), CW.copy(), CL.copy(), dict(H2H), []
    for h, a, neu, ic, cf, p in games:
        hw = p >= .5 if chalk else rng.random() < p
        wi, lo = (h, a) if hw else (a, h); add(wi, lo, ic, cf, w, l, cw, cl, h2h); res.append((h, a, wi, p))
    lost = {lo for h, a, wi, p in res for lo in (h, a) if lo != wi}
    part = {c: tuple(CCG[c]) if c in CCG else pick2(c, cw, cl, h2h) for c in CONFS}
    champ = {}
    for c, (a, b) in part.items():
        if c in ccg_done: champ[c] = ccg_done[c]; continue
        p = ph(a, b, True); champ[c] = (a if p >= .5 else b) if chalk else (a if rng.random() < p else b)
    sc = {}
    for t in FBS:
        r = RK[t] + ((5 if RK[t] <= 25 else 2) if t in lost else 0)
        for c, (a, b) in part.items():
            if t in (a, b) and c not in ccg_done: r += -2 if champ[c] == t else 2.5
        sc[t] = r + (0 if chalk else rng.normal(0, 1.5))
    order = sorted(FBS, key=lambda t: (sc[t], RK[t]))
    autos = [champ[c] for c in P4 if c in champ] + [min([champ[c] for c in G6 if c in champ], key=lambda t: sc[t])]
    field = list(dict.fromkeys(autos))
    for t in order:
        if len(field) >= 12: break
        if t not in field: field.append(t)
    return sorted(field, key=lambda t: (sc[t], RK[t])), part, champ, res
R1 = [(8, 9, 1), (5, 12, 4), (6, 11, 3), (7, 10, 2)]
def playoff(seeds, rng, cnt):
    S = dict(enumerate(seeds, 1))
    pl = lambda a, b, home=None: a if rng.random() < (ph(a, b, False) if home == a else ph(a, b, True)) else b
    r1 = {q: pl(S[h], S[a], S[h]) for h, a, q in R1}
    qf = [(S[q], r1[q]) for q in (1, 4, 3, 2)]
    for a, b in qf: cnt[a]['quarterfinal'] += 1; cnt[b]['quarterfinal'] += 1
    wq = [pl(a, b) for a, b in qf]
    for t in wq: cnt[t]['semifinal'] += 1
    f1, f2 = pl(wq[0], wq[1]), pl(wq[2], wq[3]); cnt[f1]['title game'] += 1; cnt[f2]['title game'] += 1
    cnt[pl(f1, f2)]['champion'] += 1
rng = np.random.default_rng(7); N = 20000; cnt = collections.defaultdict(collections.Counter); ccgc = collections.Counter()
fixed = st.get('bracket') or []
for _ in range(N):
    if fixed: seeds = fixed
    else:
        seeds, part, champ, _r = season(rng)
        for c, (a, b) in part.items():
            ccgc[(c, a, b)] += 1; cnt[champ[c]]['conf champ'] += 1
    for i, t in enumerate(seeds): cnt[t]['make playoff'] += 1; cnt[t]['bye'] += i < 4
    playoff(seeds, rng, cnt)
if fixed: seeds, part, champ, res = fixed, {}, {}, []
else: seeds, part, champ, res = season(rng, chalk=True)
rc = collections.defaultdict(collections.Counter); rng2 = np.random.default_rng(11); M = 200000
for _ in range(M): playoff(seeds, rng2, rc)
run = {t: [100.0 if i < 4 else round(100 * rc[t]['quarterfinal'] / M, 1)] + [round(100 * rc[t][k] / M, 1) for k in ('semifinal', 'title game', 'champion')] for i, t in enumerate(seeds)}
# ---- page
E = lambda x: html.escape(str(x)); inv = {t: i + 1 for i, t in enumerate(seeds)}; S = dict(enumerate(seeds, 1))
P = lambda a, b, home=None: ph(a, b, False) if home == a else ph(a, b, True)
fav = lambda a, b, home=None: a if P(a, b, home) >= .5 else b
chip = lambda sd, t, p, w: f'<div class="tm{" w" if w else ""}"><span class="sd">{sd}</span><span class="nm">{E(t)}</span><span class="pc">{p}</span></div>'
cols = [[], [], [], []]; w1 = {}
for h, a, q in R1:
    th, ta = S[h], S[a]; p = P(th, ta, th); w = fav(th, ta, th); w1[q] = w
    cols[0].append(f'<div class="gm"><div class="gl">First round · at {E(th)}</div>{chip(h, th, f"{p*100:.0f}%", w == th)}{chip(a, ta, f"{(1-p)*100:.0f}%", w == ta)}</div>')
wq = []
for q in (1, 4, 3, 2):
    a, b = S[q], w1[q]; p = P(a, b); w = fav(a, b); wq.append(w)
    cols[1].append(f'<div class="gm"><div class="gl">Quarterfinal</div>{chip(q, a, f"{p*100:.0f}%", w == a)}{chip(inv[b], b, f"{(1-p)*100:.0f}%", w == b)}</div>')
ws = []
for a, b in ((wq[0], wq[1]), (wq[2], wq[3])):
    p = P(a, b); w = fav(a, b); ws.append(w)
    cols[2].append(f'<div class="gm"><div class="gl">Semifinal</div>{chip(inv[a], a, f"{p*100:.0f}%", w == a)}{chip(inv[b], b, f"{(1-p)*100:.0f}%", w == b)}</div>')
a, b = ws; p = P(a, b); ch = fav(a, b)
cols[3].append(f'<div class="gm fin"><div class="gl">Title game</div>{chip(inv[a], a, f"{p*100:.0f}%", ch == a)}{chip(inv[b], b, f"{(1-p)*100:.0f}%", ch == b)}<div class="champ">Projected champion<br><b>{E(ch)}</b> · wins it all {run[ch][3]}%</div></div>')
bracket = '<div class="bk">' + ''.join(f'<div class="col">{"".join(c)}</div>' for c in cols) + '</div>'
runrows = ''.join(f'<tr><td class="n">{i}</td><td>{E(t)}</td><td class="n">{gr(t)}</td>' + ''.join(f'<td class="n"><span class="bar" style="--v:{v}"></span>{"bye" if (k == 0 and i <= 4) else f"{v:.1f}%"}</td>' for k, v in enumerate(run[t])) + '</tr>' for i, t in S.items())
pc = lambda t, k: 100 * cnt[t][k] / N
teams = sorted([t for t in cnt if pc(t, 'make playoff') >= 1], key=lambda t: (-pc(t, 'make playoff'), -pc(t, 'champion')))
fullrows = ''.join(f'<tr><td>{E(t)}</td><td class="n">{RK[t] if RK[t] <= 25 else ""}</td><td class="n">{gr(t)}</td><td class="n">{pc(t,"conf champ"):.0f}%</td><td class="n"><span class="bar" style="--v:{pc(t,"make playoff"):.1f}"></span>{pc(t,"make playoff"):.1f}%</td><td class="n">{pc(t,"bye"):.0f}%</td><td class="n">{pc(t,"semifinal"):.1f}%</td><td class="n">{pc(t,"title game"):.1f}%</td><td class="n b">{pc(t,"champion"):.1f}%</td></tr>' for t in teams)
cc = []
for c, (a, b) in part.items():
    p = ph(a, b, True); cc.append((c, a, b, champ.get(c, a if p >= .5 else b), round(100 * max(p, 1 - p))))
ccrows = ''.join(f'<tr><td>{E(c)}</td><td>{E(a)} vs {E(b)}</td><td><b>{E(x)}</b></td><td class="n">{p}%</td></tr>' for c, a, b, x, p in sorted(cc, key=lambda x: (x[0] not in P4, x[0]))) or '<tr><td colspan="4">Conference title games are done.</td></tr>'
picks = sorted([(a, h, wi, round(100 * max(p, 1 - p))) for h, a, wi, p in res if RK.get(h, 99) <= 25 or RK.get(a, 99) <= 25], key=lambda x: x[3])
wkrows = ''.join(f'<tr><td>{E(a)} at {E(h)}</td><td><b>{E(w)}</b></td><td class="n">{p}%</td></tr>' for a, h, w, p in picks) or '<tr><td colspan="3">No regular-season games left.</td></tr>'
today = datetime.date.today().strftime('%b. %-d')
page = open(TPL).read()
for k, v in {'{{BRACKET}}': bracket, '{{RUNROWS}}': runrows, '{{FULLROWS}}': fullrows, '{{CCROWS}}': ccrows, '{{WKROWS}}': wkrows,
             '{{RANKDATE}}': E(st.get('ranking_date', '')), '{{UPDATED}}': today, '{{MODE}}': 'The committee has set the bracket, so only the playoff is simulated.' if fixed else ''}.items():
    page = page.replace(k, v)
open(OUT, 'w').write(page)
print('seeds:', seeds); print('champion odds:', {t: run[t][3] for t in seeds})
