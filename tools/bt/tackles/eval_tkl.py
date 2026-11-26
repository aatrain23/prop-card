#!/usr/bin/env python3
"""Walk-forward test of tackles + assists projection variants.
For each test season S (2023-2026), the miss bands are built only from seasons 2022..S-1, and any fitted weight (spread slope)
is fit on those same seasons. Scored two ways:
  1. the 761 expert tackle picks 2023-26 (Action Network + SportsLine) at their real lines and prices: log loss, ROI of the
     picks the model rates positive at -150 or better (all, Unders only, edge >= 5 pts);
  2. every defender-game 2023-26 with a projection of 3+ tackles (about 20k games): CRPS of the model's full distribution (lower = better).
usage: python3 -I eval_tkl.py > results.json
"""
import sys, json, numpy as np, pandas as pd
sys.path.insert(0, 'scripts'); from common import load
d, t = load()
d['y'] = d.tkl
TEST = [2023, 2024, 2025, 2026]
rng = np.random.default_rng(7)

def be(o): return 100 / (o + 100) if o > 0 else -o / (-o + 100)
def pay(o): return o / 100 if o > 0 else 100 / -o
t['be'] = t.odds.map(be); t['win'] = (t.result == 'win').astype(int); t['pay'] = t.odds.map(pay)
t['prof'] = np.where(t.win == 1, t.pay, -1.0)

def bands_for(proj, mask, bypos=False):
    out = {}
    for S in TEST:
        tr = mask & d.season.between(2022, S - 1) & (proj > 0.05)
        groups = [('all', tr)] if not bypos else [(p, tr & (d.pos == p)) for p in ('LB', 'DB', 'DL')]
        for gname, m in groups:
            x = proj[m].values; yv = d.y[m].values
            qs = np.quantile(x, np.linspace(0, 1, 13)); B = []
            for i in range(12):
                sel = (x >= qs[i]) & (x <= qs[i + 1]); B.append((qs[i], qs[i + 1], np.sort(yv[sel] / x[sel])))
            out[(S, gname)] = B
    return out

def band(B, p):
    return next((b for b in B if b[0] <= p <= b[1]), B[0] if p < B[0][0] else B[-1])

def p_over(B, p, line):
    r = band(B, p)[2]; sim = r * p
    if float(line).is_integer():
        w = (sim > line + .25).mean(); l = (sim < line - .25).mean(); return w / (w + l) if w + l else np.nan
    return (sim > line).mean()

QL = np.linspace(0.01, 0.99, 50)
def crps(B, p, y):
    q = np.quantile(band(B, p)[2], QL) * p
    return 2 * np.mean(np.maximum(QL * (y - q), (QL - 1) * (y - q)))

def score(name, proj, train_mask, bypos=False, blend=None):
    proj = pd.Series(proj, index=d.index)
    Bs = bands_for(proj, train_mask, bypos)
    rows = []
    for r in t.itertuples():
        p = proj.iat[r.row]
        if not (p > 0.05) or d.gb.iat[r.row] < 3 or np.isnan(p): rows.append(np.nan); continue
        if blend is not None: p = blend * p + (1 - blend) * r.line
        B = Bs[(r.season, d.pos.iat[r.row] if bypos else 'all')]
        po = p_over(B, p, r.line); rows.append(po if r.side == 'Over' else 1 - po)
    ps = np.array(rows)
    ok = ~np.isnan(ps)
    pp = np.clip(ps[ok], .01, .99); w = t.win.values[ok]
    ll = -np.mean(w * np.log(pp) + (1 - w) * np.log(1 - pp))
    edge = ps - t.be.values
    def roi(sel): sel = sel & ok; n = sel.sum(); return dict(n=int(n), roi=float(t.prof.values[sel].mean()) if n else None, units=float(t.prof.values[sel].sum()) if n else None)
    lim = t.odds.values >= -150
    res = dict(name=name, n_picks=int(ok.sum()), logloss=float(ll),
               pos=roi((edge > 0) & lim), under=roi((edge > 0) & lim & (t.side.values == 'Under')),
               over=roi((edge > 0) & lim & (t.side.values == 'Over')), e5=roi((edge > .05) & lim))
    # big-sample CRPS on test-season games with projection 3+
    cr = [crps(Bs[(d.season.iat[i], d.pos.iat[i] if bypos else 'all')], max(proj.iat[i], .06), d.y.iat[i]) for i in SUB]
    res['crps'] = float(np.mean(cr)); res['crps_n'] = len(SUB); res['_cr'] = np.array(cr)
    res['_ps'] = ps; res['_edge'] = edge
    return res

R = []
_m = d.season.isin(TEST) & (d.gb >= 3) & (d.base_live >= 3) & d.ew_all.notna()
SUB = np.random.default_rng(7).choice(np.where(_m.values)[0], size=8000, replace=False)
live_mask = d.instats & d.base_live.notna()        # the live model trains on stats rows only
allm = d.base_live.notna()                          # same rows, but zero-tackle games included
rng = np.random.default_rng(7); base = score('Current model', d.base_live, live_mask); R.append(base)
# fixed CRPS sample: reuse the same random draw for every variant
def S(name, proj, **kw):
    global rng; rng = np.random.default_rng(7); r = score(name, proj, allm, **kw); R.append(r); return r

S('Include zero-tackle games', d.ew_all)
for c, n in [('ew_hl3', 'Half-life 3 games'), ('ew_hl4', 'Half-life 4 games'), ('ew_hl8', 'Half-life 8 games'),
             ('ew_lw4', 'Last season x0.4'), ('ew_lw8', 'Last season x0.8'), ('ew_n12', 'Last 12 games only')]:
    S(n, d[c])
exp_snaps = d.own_snaps_ew.fillna(d.team_snaps.mean())
snap = (d.rate * d.pct_proj * exp_snaps).fillna(d.ew_all)
S('Snap share (tackles/snap x expected snaps)', snap)
S('Snap share, raw snaps', (d.rate * d.snaps_proj).fillna(d.ew_all))
S('Snap share, slower rate (half-life 10)', (d.rate_hl10 * d.pct_proj * exp_snaps).fillna(d.ew_all))
volf = (d.opp_plays_ew / d.lg_plays).fillna(1).clip(.85, 1.15)
for b in (0.5, 1.0):
    S(f'Snap share + opponent plays (x{b})', snap * volf ** b)
runf = (d.opp_run_ew / d.opp_run_ew.mean()).fillna(1).clip(.8, 1.2)
S('Snap share + opponent plays + run rate (LB)', snap * volf * np.where(d.pos == 'LB', runf, 1.0))
# teammate injuries: share the newly-out starters' tackles among this player's position group (regulars only)
reg = d.pct_proj.fillna(0) >= 0.3
grp = d.assign(p=snap.where(reg, 0)).groupby(['season', 'week', 'team', 'pos']).p.transform('sum')
share = (snap / grp).where(reg, 0).fillna(0)
for a in (0.5, 1.0):
    S(f'Snap share + teammate injuries (x{a})', snap + a * d.miss_tkl * share)
S('Include zeros + teammate injuries (x0.5)', d.ew_all + 0.5 * d.miss_tkl * (d.ew_all / d.assign(p=d.ew_all.where(reg, 0)).groupby(['season', 'week', 'team', 'pos']).p.transform('sum')).where(reg, 0).fillna(0))
# spread: slope fit per season on earlier seasons, per position
def spread_adj(base_proj):
    out = base_proj.copy()
    for Sx in TEST + [2022]:
        tr = d.season.between(2021, Sx - 1) & (base_proj > 1) & d.team_spread.notna()
        for p in ('LB', 'DB', 'DL'):
            m = tr & (d.pos == p)
            if m.sum() < 500: continue
            ratio = (d.y[m] / base_proj[m]).clip(0, 4); x = d.team_spread[m]
            b = np.cov(x, ratio)[0, 1] / x.var()
            te = (d.season == Sx) & (d.pos == p)
            out[te] = base_proj[te] * (1 + b * d.team_spread[te].fillna(0)).clip(.8, 1.2)
    return out
S('Snap share + spread', spread_adj(snap))
vadj = (d.venue_f / d.venue_hist).clip(.85, 1.15)
S('Snap share + home stat crew', snap * vadj)
S('Include zeros + home stat crew', d.ew_all * vadj)
S('Snap share, bands by position', snap, bypos=True)
S('Current inputs, bands by position', d.ew_all, bypos=True)
S('Current model, bands by position (stats rows)', d.base_live, bypos=True) if False else None
for w in (0.75, 0.5):
    S(f'Snap share, blended {int(w*100)}/{int(100-w*100)} with the line', snap, blend=w)

snap10 = (d.rate_hl10 * d.pct_proj * exp_snaps).fillna(d.ew_all)
S('COMBO snap(hl10) + position bands', snap10, bypos=True)
S('COMBO snap(hl10) + opp plays 0.5 + position bands', snap10 * volf ** 0.5, bypos=True)
S('COMBO current inputs, last season x0.4, zeros, position bands', d.ew_lw4, bypos=True)
ens = 0.5 * d.ew_lw4 + 0.5 * snap10
S('COMBO 50/50 current (x0.4) + snap(hl10), position bands', ens, bypos=True)
S('COMBO 50/50 current (x0.4) + snap(hl10), one band set', ens)
ens2 = 0.5 * d.base_live + 0.5 * snap10
S('COMBO 50/50 current model + snap(hl10), position bands', ens2.fillna(d.base_live), bypos=True)

base_ps = base['_ps']
def boot(r, key='pos'):
    """paired bootstrap of log loss gain vs the current model, on picks both price"""
    ok = ~np.isnan(base_ps) & ~np.isnan(r['_ps']); w = t.win.values[ok]
    l0 = -(w * np.log(np.clip(base_ps[ok], .01, .99)) + (1 - w) * np.log(1 - np.clip(base_ps[ok], .01, .99)))
    l1 = -(w * np.log(np.clip(r['_ps'][ok], .01, .99)) + (1 - w) * np.log(1 - np.clip(r['_ps'][ok], .01, .99)))
    dlt = l0 - l1; bs = [dlt[np.random.default_rng(i).integers(0, len(dlt), len(dlt))].mean() for i in range(400)]
    return float(dlt.mean()), float(np.mean(np.array(bs) > 0))
out = []
for r in R:
    g, pr = boot(r)
    dc = base['_cr'] - r['_cr']; cb = np.mean([dc[np.random.default_rng(i).integers(0, len(dc), len(dc))].mean() > 0 for i in range(400)])
    out.append({k: v for k, v in r.items() if not k.startswith('_')} | dict(ll_gain=g, p_better=pr, crps_gain=float(dc.mean()), crps_p_better=float(cb)))
json.dump(out, sys.stdout, indent=1)
# per-season check: current vs the 50/50 blend
best = R[-1]
with open('per_season.txt', 'w') as fh:
    for S_ in TEST:
        for r in (base, best):
            ok = ~np.isnan(r['_ps']) & (t.season.values == S_); pp = np.clip(r['_ps'][ok], .01, .99); w = t.win.values[ok]
            ll = -np.mean(w * np.log(pp) + (1 - w) * np.log(1 - pp))
            sel = ok & (r['_edge'] > 0) & (t.odds.values >= -150); su = sel & (t.side.values == 'Under')
            fh.write(f"{S_} {r['name'][:40]:40s} n={ok.sum():3d} logloss={ll:.4f}  edge>0 {sel.sum():3d} {t.prof.values[sel].mean()*100:+6.1f}%  Unders {su.sum():3d} {t.prof.values[su].mean()*100:+6.1f}%\n")
