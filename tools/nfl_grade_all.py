#!/usr/bin/env python3
"""Grade every expert pick on the NFL pre-game board (Aidan, Nov 23 2026: "say if spread and over/under bets, and every prop bet
is profitable or not").

nfl_pregame_v6.py already grades the expert player props in 7 yardage/volume markets ("props"). This adds a grade to:
  * game lines ("lines"): spreads from Aidan's weekly NFL team model (nfl-data/bets.csv model_home = the model's expected
    home margin, positive = home wins by that much), using the model's own
    backtested cover rates by gap (nfl-data/tiers.csv, 2016-2026 vs closing lines). Totals and team totals: no model here beats
    the closing number (a points-rating model tested 2021-2026 won 45-48% when it disagreed with the total), so they're graded
    as a coin flip at the expert's price, which is a loss at normal juice. Moneylines (Nov 23 2026, Aidan: "add it untested"): his team model's
    expected margin turned into a win chance, P(win) = Phi(margin / 11.1) (11.0 fits closing spreads to winners 2016-2026; scaled up
    a little because his model misses margins by 9.89 points vs the market's 9.77). Not backtested against moneyline prices.
  * other props ("other_props"): anytime TD and 2+ TDs (Poisson on the player's weighted TD rate x opponent factor, calibrated
    on 2025-2026: lambda' = 0.55*lambda + 0.10), passing TDs over/milestones (lambda' = 0.5*lambda + 0.7), passing / rushing /
    receiving yards milestones and rush + rec yards (the props model's error bands), pass attempts (completions bands, approx.).
    Longest reception, "most receiving yards", first TD etc.: no model.
Player-prop grades use the expert's quoted price (no line shopping for these markets) and were never backtested against prices.

Nov 25 2026 (Aidan: "I only want to bet player props that are -150 or better"): a yardage prop whose best price on the board is
worse than -150 is re-priced here at the best-edge offer that is -150 or better within 1 point of the expert's line (Action
Network offers in an.json plus Novig offers from novig_offers.json: the optional 9th argument, else that file in the current
directory); with no such offer it becomes "no price". TD / milestone / other props quoted worse than -150 are marked over the
limit and are never "profitable". Game lines are not limited. Novig prices for game lines are read live by the board page (nfl.html).

Nov 25 2026 (later): each yardage prop also gets "venues": its best price at Novig, at Kalshi (read from the repo's kalshi-data branch,
fee included; optional 10th argument = a saved copy of that file) and at the sportsbooks, so the board can show all three.
When no sportsbook price within 1 point of the expert's line is profitable, the sportsbook entry is the best profitable line at
any distance (alt lines included, -150 or better), marked "alt": true; it is a fallback only and never changes the prop's status.

Nov 26 2026 (Aidan: "If you're giving under bets, only give the line an expert gives" ... "just use the experts lines for both"):
then "use the expert lines if one makes a big difference ... for receiving yardage it wouldnt": count props (receptions, rush
attempts, pass completions, tackles + assists) are priced only at the expert's own line (the alt-line sportsbook fallback too);
yardage props (receiving, rushing, passing yards) use the best-edge line within 5% of it, higher or lower ("can be up or
down to the line you find most profitable").

Nov 26 2026 (Aidan: "only look at prop bets for games that haven't happened yet"): games on the board that have already kicked off
are left exactly as they were graded before kickoff (no re-pricing, no re-grading), so live in-game prices never turn a pick "profitable".

Nov 26 2026 (Aidan: "Yes", after the tackles backtest): tackles + assists UNDERS use a new projection: 50/50 the current projection
(nfl_pregame_v6.py's model_proj) and a snap-share projection (tackles per defensive snap, half-life 10 games, x his expected snap share,
half-life 2 games, x his defense's snaps per game, half-life 4 games; nflverse snap counts), priced with miss bands by position group
(nfl-data/tkl_under_bands.json). Walk-forward 2023-26 on 754 expert tackle picks: log loss 0.678 -> 0.669 (better every season);
model-positive Unders at -150 or better +15.2% -> +22.2% a bet (247 -> 254 bets, better every season). Tackle OVERS keep the current
model (the blend made them worse, small sample). If the snap counts can't be downloaded, Unders fall back to the current model.

usage: python3 -I nfl_grade_all.py board.json an.json sl.json|- stats_prev.csv stats_cur.csv bands.json bets.csv tiers.csv [novig_offers.json [kalshi-nfl-props.json]] > board_graded.json
"""
import sys, os, json, re, math, unicodedata, bisect, csv, datetime

TEAMFIX = {'JAC': 'JAX', 'LAR': 'LA', 'WSH': 'WAS'}
ATD_A, ATD_B = 0.55, 0.10      # anytime-TD lambda calibration (2025-2026 walk-forward, players with lambda > 0.08)
PTD_A, PTD_B = 0.50, 0.70      # passing-TD lambda calibration (QBs, same test)
ML_SIGMA = 11.1
# Nov 25 2026 backtest (tools/bt/td_model.py, 2023-2026, week 4 on, walk-forward): betting every anytime TD the model rated above
# the market price lost 25.5% a bet (7,717 bets; every season -15% to -29%; under +500 still -7.6%); hit rates followed the price,
# not the model. So TD scorer props are shown with the model's chance but status "no edge", never "profitable".
TD_NOTE = "No backtested edge: betting the model's anytime TD edges lost 25% a bet in a 2023-26 backtest (the price beat the model)."
TOTAL_NOTE = "No model here beats the closing total (tested 2021-2026: 45-48% when it disagreed), so this is a coin flip at the posted price."


def norm(n):
    n = ''.join(c for c in unicodedata.normalize('NFD', n or '') if unicodedata.category(c) != 'Mn').lower()
    n = re.sub(r"[.'’`]", '', n); n = re.sub(r'[^a-z ]', ' ', n)
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return ' '.join(n.split())


def be(o): return 100 / (o + 100) if o > 0 else -o / (-o + 100)
def tm(t): return TEAMFIX.get(t, t)


LIMIT = -150     # Aidan, Nov 25 2026: player props only at -150 or better
WIN = 50.0       # Aidan, Nov 25 2026: player props are half a unit = to win $50 (1 unit = to win $100; nfl_pregame_v6.py still sizes at $25, re-sized here)
BOOKS = {69: 'FanDuel', 75: 'BetMGM', 49: 'Caesars', 2988: 'Fanatics', 4620: 'theScore Bet'}
AN_MK = {'core_bet_type_16_receiving_yards': 'rec_yds', 'core_bet_type_12_rushing_yards': 'rush_yds',
         'core_bet_type_10_pass_completions': 'pass_cmp', 'core_bet_type_70_tackles_assists': 'tkl',
         'core_bet_type_15_receptions': 'rec', 'core_bet_type_9_passing_yards': 'pass_yds', 'core_bet_type_18_rushing_attempts': 'rush_att'}
STAT_KEY = {'receiving yards': 'rec_yds', 'rushing yards': 'rush_yds', 'pass completions': 'pass_cmp', 'tackles + assists': 'tkl',
            'receptions': 'rec', 'passing yards': 'pass_yds', 'rush attempts': 'rush_att'}


YARD_MK = {'rec_yds', 'rush_yds', 'pass_yds'}
YARD_PCT = 0.05   # Nov 26 2026 (Aidan): every prop within 5% of the expert's line, higher or lower (a 3.5 line allows only 3.5)
def line_ok(line, el, under, stat):
    # Nov 26 2026 (Aidan: "I guess the 5% rule can apply to all bets"): every prop, count or yardage, within 5% of the expert's line
    # Aidan: yardage "can be up or down to the line you find most profitable"; window = 5% of the expert's line ("a certain percentage", he chose 5%)
    return abs(line - el) <= YARD_PCT * abs(el) + 1e-9


KALSHI_URL = 'https://raw.githubusercontent.com/aatrain23/prop-card/kalshi-data/kalshi-nfl-props.json'   # written every 10 minutes by .github/workflows/kalshi.yml
KALSHI_STAT = {'passyds': 'pass_yds', 'comp': 'pass_cmp', 'rushyds': 'rush_yds', 'rushatt': 'rush_att', 'recyds': 'rec_yds', 'rec': 'rec'}   # Kalshi lists no tackles


def american(p): return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def load_kalshi(kf):
    """Kalshi NFL player-prop asks -> {(YYMMMDD, player, stat, side): [offers]}. The price is the ask plus Kalshi's taker fee
    (0.07 x P x (1 - P), the Line Shop's estimate) as American odds. Asks outside 2-98 cents count as no price. Returns ({}, why) if unusable."""
    import subprocess, datetime
    try:
        if kf and os.path.exists(kf): d = json.load(open(kf))
        else: d = json.loads(subprocess.run(['curl', '-sSfL', '--max-time', '40', KALSHI_URL], capture_output=True, text=True, check=True).stdout)
        up = datetime.datetime.fromisoformat(d['updated'].replace('Z', '+00:00'))
        age = (datetime.datetime.now(datetime.timezone.utc) - up).total_seconds() / 60
        if age > 90 and not (kf and os.path.exists(kf)): return {}, f'Kalshi prices are {age:.0f} minutes old: not used'
    except Exception as e:
        return {}, f'Kalshi prices could not be read ({str(e)[:80]})'
    K = {}
    for p in d.get('props', []):
        st = KALSHI_STAT.get(p.get('stat'))
        if not st or p.get('line') is None: continue
        for side, ask in (('Over', p.get('ya')), ('Under', p.get('na'))):
            if ask is None or not (0.02 < ask < 0.98): continue
            eff = min(0.99, ask + 0.07 * ask * (1 - ask))
            K.setdefault((str(p.get('game', ''))[:7], norm(p.get('player', '')), st, side), []).append(dict(book='Kalshi', line=float(p['line']), odds=float(american(eff))))
    return K, f"Kalshi: {sum(len(v) for v in K.values())} prices, updated {d.get('updated')}"


def price_venues(B, AN, bands, nvf, kf=None):
    """Every yardage prop priced three ways (Aidan, Nov 25 2026: "give the line for that bet at kalshi/novig as well as a sportsbook
    if there is no liquidity on the sites"): p['venues'] = {novig, kalshi, book}, each the best-edge offer at LIMIT or better within
    1 point of the expert's line (None when that place has no such price), and p['best'] = the best of the three.
    The gold "bet" pick keeps its status; every other prop is profitable / negative / no model / no price by its best price."""
    import datetime
    from zoneinfo import ZoneInfo
    pname = {int(k): v[0] for k, v in AN.get('players', {}).items()}
    offers = {}
    for book, t, gid, plid, side, val, odds, alt in AN.get('offers', []):
        if t not in AN_MK or book not in BOOKS or val is None or odds is None or side not in ('under', 'over'): continue
        offers.setdefault((gid, norm(pname.get(plid, '')), AN_MK[t], side.title()), []).append(dict(book=BOOKS[book], line=float(val), odds=float(odds)))
    if nvf and os.path.exists(nvf):
        for o in json.load(open(nvf)):
            if o.get('game_id') is None or o.get('stat') not in AN_MK.values(): continue
            offers.setdefault((int(o['game_id']), norm(o['player']), o['stat'], o['side']), []).append(dict(book='Novig', line=float(o['line']), odds=float(o['odds'])))
    else:
        print('novig offers file not found: props priced without Novig', file=sys.stderr)
    K, kmsg = load_kalshi(kf); print(kmsg, file=sys.stderr)
    B['venues_note'] = ('Novig and Kalshi prices are their asks when the board was built (Kalshi includes its fee; Novig charges none before kickoff). '
                        'A place shows "no price" when it has nothing at -150 or better at the expert\'s line (within 5% of it).' + ('' if K else ' ' + kmsg + '.'))
    moved = gone = 0
    for g in B.get('games', []):
        day = datetime.datetime.fromisoformat(g['start'].replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York')).strftime('%y%b%d').upper()
        for p in g.get('props', []):
            s = STAT_KEY.get(p.get('stat')); el = float(p['expert_line']); under = p['side'] == 'Under'; proj = p.get('model_proj')
            sb = p.get('band_key') if p.get('band_key') in bands else s   # tackle Unders: position bands (Nov 26 2026)
            allo = offers.get((g['id'], norm(p['player']), s, p['side']), []) + K.get((day, norm(p['player']), s, p['side']), [])
            # Nov 26 2026 (Aidan): every prop within 5% of the expert's line (see line_ok)
            ok = [dict(o) for o in allo if o['odds'] >= LIMIT and line_ok(o['line'], el, under, s)]
            for o in ok:
                po = p_over(bands, sb, proj, o['line']) if proj is not None else None
                o['p'] = None if po is None else (1 - po if under else po); o['edge'] = None if po is None else o['p'] - be(o['odds'])
            def top(L):
                if not L: return None
                rated = [o for o in L if o['edge'] is not None]
                bo = max(rated, key=lambda o: (o['edge'], o['odds'])) if rated else max(L, key=lambda o: (o['line'] if under else -o['line'], o['odds']))
                return dict(book=bo['book'], line=bo['line'], odds=int(bo['odds']), edge=None if bo['edge'] is None else round(bo['edge'], 3),
                            p=None if bo['p'] is None else round(bo['p'], 3),
                            stake=round(WIN * (-bo['odds']) / 100, 2) if bo['odds'] < 0 else round(WIN * 100 / bo['odds'], 2))
            bk = top([o for o in ok if o['book'] not in ('Novig', 'Kalshi')])
            # Nov 25 2026 (Aidan): "If Novig or Kalshi is using an alt line, find a line at a sportsbook that is profitable if there
            # is one" (e.g. Jordan Love Under 265). When no sportsbook price near the expert's line is profitable, search every line
            # the sportsbooks offer (alt lines included, any distance from the expert's line) at -150 or better, and keep the
            # best-edge profitable one, marked alt=True. Shown as the sportsbook fallback only; it never changes the prop's status.
            if proj is not None and not (bk and (bk['edge'] or 0) > 0):
                alt = [dict(o) for o in allo if o['book'] not in ('Novig', 'Kalshi') and o['odds'] >= LIMIT and line_ok(o['line'], el, under, s)]   # within 5% of the expert's line (Nov 26 2026)
                for o in alt:
                    po = p_over(bands, sb, proj, o['line'])
                    o['p'] = None if po is None else (1 - po if under else po); o['edge'] = None if po is None else o['p'] - be(o['odds'])
                alt = [o for o in alt if o['edge'] is not None and o['edge'] > 0]
                if alt:
                    bk = top(alt); bk['alt'] = True
            p['venues'] = dict(novig=top([o for o in ok if o['book'] == 'Novig']), kalshi=top([o for o in ok if o['book'] == 'Kalshi']), book=bk)
            old = p.get('best'); nb = top(ok)
            if (old or {}).get('odds') != (nb or {}).get('odds') or (old or {}).get('book') != (nb or {}).get('book'): moved += 1
            p['best'] = nb; p['price_ok'] = bool(nb)
            if not nb: gone += 1
            if p.get('status') == 'bet' and nb and (nb['edge'] or 0) > 0: continue
            p['status'] = 'no price' if not nb else 'no model' if nb['edge'] is None else 'profitable' if nb['edge'] > 0 else 'negative'
        order = ['bet', 'profitable', 'negative', 'no model', 'no price']
        g.get('props', []).sort(key=lambda p: (order.index(p['status']) if p['status'] in order else 9, -((p.get('best') or {}).get('edge') or -9)))
    return moved, gone




# ---------- tackles + assists Unders: 50/50 current projection + snap-share projection (Nov 26 2026 backtest) ----------
TKL_BANDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nfl-data', 'tkl_under_bands.json')
def _ew(vals, seas, cur, hl, lw, n):
    vals, seas = vals[-n:], seas[-n:]
    k = len(vals); w = [0.5 ** ((k - 1 - i) / hl) * (1.0 if seas[i] == cur else lw) for i in range(k)]
    return sum(a * b for a, b in zip(w, vals)) / sum(w)
def tkl_blend(B, stats_files, season, bands):
    """Re-project tackle Unders on the board. Adds the position bands to `bands`; returns a status line."""
    import subprocess, tempfile, pandas as pd
    unders = [p for g in B.get('games', []) for p in g.get('props', []) if p.get('stat') == 'tackles + assists' and p.get('side') == 'Under'
              and p.get('model_proj') is not None]
    if not unders: return 'tackle Unders: none on the board'
    try: TB = json.load(open(TKL_BANDS))
    except Exception as e: return f'tackle Unders: bands file missing ({e}); current model kept'
    tmp = tempfile.mkdtemp(); snaps = []
    for y in (season - 1, season):
        f = os.path.join(tmp, f'snaps_{y}.csv')
        r = subprocess.run(['curl', '-sfL', '--max-time', '60', '-o', f, f'https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{y}.csv'])
        if r.returncode == 0 and os.path.getsize(f) > 1000: snaps.append(pd.read_csv(f))
    if not snaps or not any((x.season == season).any() for x in snaps): return "tackle Unders: couldn't download this season's snap counts; current model kept"
    sn = pd.concat(snaps, ignore_index=True); sn = sn[(sn.game_type == 'REG') & (sn.defense_snaps > 0)].copy()
    sn['team'] = sn.team.map(tm); sn['key'] = sn.player.fillna('').astype(str).map(norm)
    st = pd.concat([pd.read_csv(f, low_memory=False) for f in dict.fromkeys(stats_files)], ignore_index=True)
    st = st[st.season_type == 'REG'].copy()
    for c in ('def_tackles_solo', 'def_tackle_assists', 'def_tackles_with_assist'): st[c] = pd.to_numeric(st[c], errors='coerce').fillna(0)
    st['tkl'] = st.def_tackles_solo + st.def_tackle_assists + st.def_tackles_with_assist   # how books graded 99% of the backtest picks
    st['key'] = st.player_display_name.fillna('').astype(str).map(norm); st['team'] = st.team.map(tm)
    st['pos'] = st.position_group.fillna(st.position)
    tk = st.groupby(['season', 'week', 'team', 'key']).tkl.sum()
    sn['tkl'] = [tk.get((a, b, c, d), 0.0) for a, b, c, d in zip(sn.season, sn.week, sn.team, sn.key)]
    sn['t'] = sn.season * 100 + sn.week
    team_snaps = sn.groupby(['team', 't', 'season']).defense_snaps.max().reset_index().sort_values('t')
    pos_of = st.sort_values(['season', 'week']).groupby(['key', 'team']).pos.last().to_dict()
    for k, v in TB.items():
        if k.startswith('tkl_u_'): bands[k] = v
    done = 0
    for g in B.get('games', []):
        for p in g.get('props', []):
            if p not in unders: continue
            k, team = norm(p['player']), tm(p.get('team') or '')
            x = sn[(sn.key == k) & ((sn.team == team) if team else True)].sort_values('t')
            pos = pos_of.get((k, team)) or (st[st.key == k].pos.iloc[-1] if (st.key == k).any() else None)
            if x.empty or pos not in ('LB', 'DB', 'DL'):
                p['tkl_note'] = 'current model (no snap data)'; continue
            se = x.season.tolist(); cur = season
            v, sv = x.tkl.tolist()[-24:], x.defense_snaps.tolist()[-24:]; ss = se[-24:]; kk = len(v)
            w = [0.5 ** ((kk - 1 - i) / 10.0) * (1.0 if ss[i] == cur else 0.6) for i in range(kk)]
            rate = sum(a * b for a, b in zip(w, v)) / max(sum(a * b for a, b in zip(w, sv)), 1)
            pct = _ew(x.defense_pct.tolist(), se, cur, 2.0, 0.6, 8)
            ts = team_snaps[team_snaps.team == (x.team.iloc[-1])]
            own = _ew(ts.defense_snaps.tolist(), ts.season.tolist(), cur, 4.0, 0.5, 16) if len(ts) else 64.4
            snap = rate * pct * own; old = float(p.get('model_proj_old', p['model_proj']))   # a game carried over from an earlier run is not blended twice
            p['model_proj_old'] = old; p['model_proj_snap'] = round(snap, 2)
            p['model_proj'] = round(0.5 * old + 0.5 * snap, 2); p['band_key'] = 'tkl_u_' + pos
            p['tkl_note'] = f'blend: current {old:.1f}, snap share {snap:.1f} ({rate:.3f} a snap x {pct * 100:.0f}% x {own:.0f} snaps)'
            done += 1
    return f'tackle Unders: {done} of {len(unders)} re-projected with the snap-share blend'


def grade(p, odds, note='', model=None):
    if p is None or odds in (None, '') or not isinstance(odds, (int, float)) or abs(odds) < 100:
        return dict(status='no model', note=note)
    e = p - be(odds)
    return dict(p=round(p, 3), be=round(be(odds), 3), edge=round(e, 3), odds=odds, status='profitable' if e > 0 else 'negative', note=note, model=model)


# ---------- player projections (same weighting as the props model: half-life 6 games, last season x0.6, last 24 games) ----------
def build(stats_files):
    import pandas as pd, numpy as np
    df = pd.concat([pd.read_csv(f, low_memory=False) for f in dict.fromkeys(stats_files)], ignore_index=True)
    df = df[df.season_type == 'REG'].copy()
    cols = ['passing_yards', 'rushing_yards', 'receiving_yards', 'attempts', 'completions', 'passing_tds', 'rushing_tds', 'receiving_tds', 'receptions', 'carries']
    for c in cols: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    df['td'] = df.rushing_tds + df.receiving_tds
    df['rr'] = df.rushing_yards + df.receiving_yards
    df['pos'] = df.position_group.fillna(df.position)
    df['t'] = df.season * 100 + df.week
    S = ['passing_yards', 'rushing_yards', 'receiving_yards', 'attempts', 'completions', 'passing_tds', 'td', 'rr', 'receptions']
    cur = int(df.season.max())
    P = {}
    for pid, g in df.sort_values('t').groupby('player_id'):
        if (g.season == cur).sum() < 3: continue
        X = g[S].values.astype(float)[-24:]; seas = g.season.values[-24:]
        w = 0.5 ** (np.arange(len(X) - 1, -1, -1) / 6.0) * np.where(seas == cur, 1.0, 0.6)
        m = (w[:, None] * X).sum(0) / w.sum(); last = g.iloc[-1]
        P.setdefault(norm(last.player_display_name), []).append(dict(team=tm(last.team), pos=last.pos, name=last.player_display_name, m=dict(zip(S, map(float, m)))))
    c = df[df.season == cur]
    al = c.groupby(['opponent_team', 'pos', 'week'])[S].sum().reset_index()
    per = al.groupby(['opponent_team', 'pos'])[S].mean(); n = al.groupby(['opponent_team', 'pos']).size(); lg = al.groupby('pos')[S].mean()
    F = {}
    for (opp, pos), row in per.iterrows():
        k = n[(opp, pos)]
        for s in S:
            L = lg.loc[pos, s]
            F[(tm(opp), pos, s)] = float(min(1.35, max(0.7, ((row[s] / L) * k + 6) / (k + 6)))) if L > 0 else 1.0
    return P, F


def p_over(bands, s, proj, line):
    B = bands.get(s)
    if not B or proj <= 0.05: return None
    b = next((b for b in B if b[0] <= proj <= b[1]), B[0] if proj < B[0][0] else B[-1])
    q = b[2]; i = bisect.bisect_right(q, line / proj)
    return 1 - i / len(q)


def pois_ge(lam, k):   # P(X >= k)
    return 1 - sum(math.exp(-lam) * lam ** j / math.factorial(j) for j in range(k))


# ---------- parsing the other props ----------
def parse(play, market=None):
    """-> (kind, side, line) or None. kind: atd, td2, ptd, pyds, ryds, recyds, rr, patt"""
    s = play
    if market:   # SportsLine: market name + "Name Over 2.5 -121"
        m = re.match(r'^(.*?)\s+(Over|Under)\s+(\d+(?:\.\d+)?)', s)
        K = {'TOTAL_PASSING_TOUCHDOWNS': 'ptd', 'TOTAL_PASSING_ATTEMPTS': 'patt', 'TOTAL_RUSHING_AND_RECEIVING_YARDS': 'rr'}.get(market)
        if m and K: return m.group(1), K, m.group(2), float(m.group(3))
        m = re.match(r'^(.*?)\s+Anytime Touchdown', s)
        if m: return m.group(1), 'atd', 'Over', 0.5
        return None
    pats = [(r'^(.*?) Anytime TD Scorer Yes', 'atd', 'Over', lambda m: 0.5),
            (r'^(.*?) 2\+ TDs Yes', 'td2', 'Over', lambda m: 1.5),
            (r'^(.*?) ([ou])(\d+(?:\.\d+)?) Pass TDs', 'ptd', None, lambda m: float(m.group(3))),
            (r'^(.*?) ([ou])(\d+(?:\.\d+)?) Pass Att', 'patt', None, lambda m: float(m.group(3))),
            (r'^(.*?) ([ou])(\d+(?:\.\d+)?) Rush \+ Rec Yds', 'rr', None, lambda m: float(m.group(3))),
            (r'^(.*?) (\d+)\+ Passing Touchdowns Yes', 'ptd', 'Over', lambda m: float(m.group(2)) - 0.5),
            (r'^(.*?) (\d+)\+ Passing Yards Yes', 'pyds', 'Over', lambda m: float(m.group(2)) - 0.5),
            (r'^(.*?) (\d+)\+ Rushing Yards Yes', 'ryds', 'Over', lambda m: float(m.group(2)) - 0.5),
            (r'^(.*?) (\d+)\+ Receiving Yards Yes', 'recyds', 'Over', lambda m: float(m.group(2)) - 0.5)]
    for rx, kind, side, ln in pats:
        m = re.match(rx, s)
        if m:
            sd = side or ('Over' if m.group(2) == 'o' else 'Under')
            return m.group(1), kind, sd, ln(m)
    return None


def find_player(P, name, teams):
    """name is 'Joe Burrow' or 'J.Burrow'; teams = the game's two teams."""
    cands = []
    if '.' in name and ' ' not in name.strip():
        ini, last = name.split('.', 1); last = norm(last)
        for k, v in P.items():
            parts = k.split()
            if parts and parts[-1] == last.split()[-1] and k.startswith(norm(ini)[:1]): cands += v
    else:
        cands = P.get(norm(name), [])
    cands = [c for c in cands if c['team'] in teams]
    return cands[0] if len(cands) == 1 else None


def grade_prop(P, F, bands, play, odds, teams, market=None):
    r = parse(play, market)
    if not r: return dict(status='no model', note='No model for this market.')
    name, kind, side, line = r
    pl = find_player(P, name, teams)
    if not pl: return dict(status='no model', note='Player not found in this season\'s stats.')
    opp = [t for t in teams if t != pl['team']][0]
    f = lambda s: F.get((opp, pl['pos'], s), 1.0)
    m = pl['m']
    if kind in ('atd', 'td2'):
        lam = ATD_A * m['td'] * f('td') + ATD_B
        p = pois_ge(lam, 1 if kind == 'atd' else 2)
        note = f"Model: {m['td']:.2f} rush + rec TDs a game (weighted), opponent factor {f('td'):.2f}; calibrated on 2025-2026."
    elif kind == 'ptd':
        lam = PTD_A * m['passing_tds'] * f('passing_tds') + PTD_B
        p = pois_ge(lam, int(math.floor(line)) + 1)
        note = f"Model: {m['passing_tds']:.2f} passing TDs a game (weighted), expects {lam:.2f} here after calibration."
    else:
        st, band = {'pyds': ('passing_yards', 'pass_yds'), 'ryds': ('rushing_yards', 'rush_yds'), 'recyds': ('receiving_yards', 'rec_yds'),
                    'patt': ('attempts', 'pass_cmp'), 'rr': ('rr', None)}[kind]
        proj = m[st] * f(st)
        if band is None: band = 'rush_yds' if m['rushing_yards'] >= m['receiving_yards'] else 'rec_yds'
        p = p_over(bands, band, proj, line)
        if p is None: return dict(status='no model', note='No projection.')
        note = f"Model projection {proj:.1f}" + (' (attempts use the completions error bands, approximate)' if kind == 'patt' else ' (uses the main error bands of his bigger yardage stat)' if kind == 'rr' else '') + '.'
    p = p if side == 'Over' else 1 - p
    if kind in ('atd', 'td2'):   # Aidan, Nov 25 2026: TD scorer props are never "profitable" (see TD_NOTE)
        g = grade(p, odds, note, model=None)
        if g.get('status') in ('profitable', 'negative'): g.update(status='no edge', td_bt=True)
        g['note'] = TD_NOTE + ' ' + note
        return g
    return grade(p, odds, note + " At the expert's price; not backtested against prices.", model=None)


# ---------- profitable analysts only (Aidan, Nov 24 2026: "only include them in github if they're profitable for either CFB, NFL, UFC,
# or a combination"). experts.json (built by tools/build_experts.py) says who is kept; analysts not in it are left off the board.
def _enorm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', s.lower())


def load_experts():
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'experts.json')
    try:
        return json.load(open(f))
    except Exception as e:
        print(f'experts.json not read ({e}); analysts not filtered', file=sys.stderr)
        return None


def expert_ok(E, src, name, user=None):
    n = str(name or ''); m = re.search(r'\s*\((Action Network|SportsLine)\)\s*$', n)
    if m: src = src or m.group(1); n = n[:m.start()]
    s = 'an' if re.match(r'(an|action)', src or '', re.I) else 'sl' if re.match(r'(sl|sports)', src or '', re.I) else ''
    k, u = _enorm(n), str(user or '').lower()
    if s in ('', 'an') and u and u in E['an_users'] and E['an_users'][u] in E['an']:
        return E['an'][E['an_users'][u]]['ok']
    hits = [E[x][k]['ok'] for x in ([s] if s else ['an', 'sl']) if k in E[x]]
    return any(hits)


# NFL player props (Aidan, Nov 26 2026: "profitable betters only", after the every-prop backtest): props and other props are kept
# only for analysts up on their own NFL player-prop record (experts.json "nflprop", 50+ graded prop picks). Game lines keep expert_ok.
def expert_prop_ok(E, src, name):
    P = E.get('nflprop')
    if not P: return expert_ok(E, src, name)
    n = str(name or ''); m = re.search(r'\s*\((Action Network|SportsLine)\)\s*$', n)
    if m: src = src or m.group(1); n = n[:m.start()]
    s = 'an' if re.match(r'(an|action)', src or '', re.I) else 'sl' if re.match(r'(sl|sports)', src or '', re.I) else ''
    k = _enorm(n)
    return any(P[x].get(k, {}).get('ok') for x in ([s] if s else ['an', 'sl']))


def filter_board(B, E):
    if not E: return 0
    dropped = 0
    for g in B.get('games', []):
        keep = []
        for p in g.get('props', []):
            ex = [x for x in (p.get('experts') or []) if expert_prop_ok(E, '', x)]
            if not ex: dropped += 1; continue
            if len(ex) < len(p.get('experts') or []):
                names = {re.sub(r'\s*\((Action Network|SportsLine)\)\s*$', '', x) for x in ex}
                p['why'] = [w for w in (p.get('why') or []) if str(w).split(':', 1)[0].strip() in names]
            p['experts'] = ex; p['n_experts'] = len(ex); keep.append(p)
        g['props'] = keep
        for key in ('other_props', 'lines'):
            before = len(g.get(key, []))
            ok = (lambda o: expert_prop_ok(E, o.get('src'), o.get('expert'))) if key == 'other_props' else (lambda o: expert_ok(E, o.get('src'), o.get('expert'), o.get('user')))
            g[key] = [o for o in g.get(key, []) if ok(o)]
            dropped += before - len(g[key])
    B['experts_note'] = ('Player props: only analysts up on their own NFL prop record (50+ picks' + (f", through {E['nflprop']['through']}" if E.get('nflprop') else '') +
                         '). Game lines: analysts profitable in CFB, NFL or UFC (or the three combined). See experts.json.')
    return dropped


# ---------- analysts split (Aidan, Nov 26 2026: "add a rule to not include prop bets if analysts disagree") ----------
# When any analysts (Action Network or SportsLine, before the profitable-analyst filter) take the Over and others the Under on the
# same player and stat in a game (milestones count as Overs), every pick on that player and stat is left off the board. The game
# keeps a "split" list and the board note names them, so it's clear why they're missing.
def drop_split(B):
    dropped = 0
    for g in B.get('games', []):
        sides = {}
        key = lambda name, stat: (norm(name or ''), str(stat or '').strip().lower())
        for p in g.get('props', []):
            sides.setdefault(key(p.get('player'), p.get('stat')), {}).setdefault(p.get('side'), []).extend(p.get('experts') or [])
        for o in g.get('other_props', []):
            b = o.get('bet') or {}
            if b.get('name') and b.get('side') in ('Over', 'Under'):
                sides.setdefault(key(b['name'], b.get('stat')), {}).setdefault(b['side'], []).append(f"{o.get('expert')} ({o.get('src')})")
        split = {k: v for k, v in sides.items() if v.get('Over') and v.get('Under')}
        if not split: continue
        g['split'] = []
        for k, v in split.items():
            nm = next((p['player'] for p in g.get('props', []) if key(p.get('player'), p.get('stat')) == k), None) or \
                 next(((o.get('bet') or {}).get('name') for o in g.get('other_props', []) if key((o.get('bet') or {}).get('name'), (o.get('bet') or {}).get('stat')) == k), k[0])
            g['split'].append(dict(player=nm, stat=k[1], over=sorted(set(v['Over'])), under=sorted(set(v['Under']))))
        before = len(g.get('props', [])) + len(g.get('other_props', []))
        g['props'] = [p for p in g.get('props', []) if key(p.get('player'), p.get('stat')) not in split]
        g['other_props'] = [o for o in g.get('other_props', []) if key((o.get('bet') or {}).get('name'), (o.get('bet') or {}).get('stat')) not in split]
        dropped += before - len(g['props']) - len(g['other_props'])
    names = [f"{s['player']} {s['stat']}" for g in B.get('games', []) for s in g.get('split', [])]
    if names:
        B['note'] = (B.get('note') or '').rstrip() + ' Left off because analysts disagree (some Over, some Under): ' + '; '.join(names) + '.'
    return dropped


# ---------- game lines ----------
def load_tiers(f):
    T = {}
    for r in csv.DictReader(open(f)):
        T[r['grade']] = float(r['cover']) / 100
    return T


def spread_grade(model_home, side_home, H, odds, T):
    """H = the spread on the home team (negative = home favored). model_home = the model's expected home margin."""
    gap = (model_home + H) if side_home else -(model_home + H)
    a = abs(gap)
    tier = 'A' if a >= 5 else 'B' if a >= 3 else 'C' if a >= 1.5 else 'D'
    rate = T.get(tier, 0.5) if tier != 'D' else 0.5
    p = rate if gap > 0 else (1 - rate if tier != 'D' else 0.5)
    note = (f"Your team model has this side by {a:.1f} points (grade {tier}: its side covered {rate * 100:.1f}% vs closing lines, 2016-2026)." if gap > 0 and tier != 'D'
            else f"Your team model is {a:.1f} points the other way (grade {tier} side covered {rate * 100:.1f}%)." if tier != 'D'
            else f"Your team model is within {a:.1f} points of this line (grade D: no edge).")
    return grade(p, odds, note, model=model_home)


STAT = {'atd': 'Anytime TD', 'td2': 'Touchdowns', 'ptd': 'Passing TDs', 'pyds': 'Passing Yards', 'ryds': 'Rushing Yards', 'recyds': 'Receiving Yards',
        'rr': 'Rush + Rec Yards', 'patt': 'Pass Attempts'}
SL_AN = {'TOTAL_PASSING_TOUCHDOWNS': 'core_bet_type_11_passing_tds', 'TOTAL_PASSING_ATTEMPTS': 'core_bet_type_30_passing_attempts',
         'TOTAL_RUSHING_AND_RECEIVING_YARDS': 'core_bet_type_66_rushing_receiving_yards'}


def bet_fields(o, an, teams, market):
    """What the board needs to price this prop live at his books (Action Network market type, player id, side, value) and to log it
    (full name, team, stat, side, line in the card's terms)."""
    r = parse(o.get('play', ''), market)
    if not r: return None
    name, kind, side, line = r
    m = dict(stat=STAT[kind], side=side, line=line)
    AT = an.get('teams', {}); PL = an.get('players', {})
    if o.get('src') == 'Action Network':
        pk = next((p for p in an.get('picks', []) if p[4] == o.get('play')), None)
        if pk:
            pid = str(pk[8]); pl = PL.get(pid)
            m.update(type=pk[3], pid=pk[8], an_side=(pk[5] or '').lower() if (pk[5] or '').lower() in ('over', 'under') else 'noside', an_value=pk[6])
            if pl: m.update(name=pl[0], team=tm(AT.get(str(pl[1]), '')))
    else:
        want = norm(name)
        pid = next((k for k, v in PL.items() if norm(v[0]) == want and tm(AT.get(str(v[1]), '')) in teams), None)
        if pid:
            m.update(name=PL[pid][0], team=tm(AT.get(str(PL[pid][1]), '')), pid=int(pid))
        if kind == 'atd': m.update(type='core_bet_type_62_anytime_touchdown_scorer', an_side='noside', an_value=0)
        elif market in SL_AN: m.update(type=SL_AN[market], an_side=side.lower(), an_value=line)
    return m


def main(boardf, anf, slf, s1, s2, bandsf, betsf, tiersf, nvf='novig_offers.json', kf=None):
    B = json.load(open(boardf)); bands = json.load(open(bandsf))
    # Nov 26 2026 (Aidan: "only look at prop bets for games that haven't happened yet"): a game that has already kicked off keeps
    # the grades it had when it was graded before kickoff. It is set aside here and never re-priced (Kalshi/Novig/book prices after
    # kickoff are live in-game prices), then put back in kickoff order.
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    def _started(g):
        try: return datetime.datetime.fromisoformat(str(g.get('start', '')).replace('Z', '+00:00')) <= now_utc
        except ValueError: return False
    held = [g for g in B.get('games', []) if _started(g)]
    B['games'] = [g for g in B.get('games', []) if not _started(g)]
    if held: print(f"kept {len(held)} game(s) that already kicked off as graded before kickoff: {', '.join(g.get('game', '') for g in held)}", file=sys.stderr)
    P, F = build([s1, s2]); T = load_tiers(tiersf)
    sl = json.load(open(slf)).get('picks', []) if slf != '-' else []
    AN = json.load(open(anf))
    B['season'], B['week'] = AN.get('season'), AN.get('week')
    M = {}
    for r in csv.DictReader(open(betsf)):
        try: M[r['matchup'].replace(' ', '')] = float(r['model_home'])
        except (ValueError, KeyError): pass
    n = dict(lines=0, props=0, profitable=0)
    try: print(tkl_blend(B, [s1, s2], int(AN.get('season') or 0), bands), file=sys.stderr)
    except Exception as e: print(f'tackle Unders: blend failed ({e}); current model kept', file=sys.stderr)
    moved, gone = price_venues(B, AN, bands, nvf, kf)
    print(f'props priced at Novig, Kalshi and the sportsbooks (-150 or better): {moved} best prices changed, {gone} with no price', file=sys.stderr)
    for g in B.get('games', []):
        teams = [tm(g['away']), tm(g['home'])]
        mh = M.get(f"{g['away']}@{g['home']}".replace(' ', '')) or M.get(f"{teams[0]}@{teams[1]}")
        g['model_home'] = mh
        for l in g.get('lines', []):
            odds = l.get('odds'); odds = float(odds) if odds not in (None, '') else None
            if l['market'] == 'spread' and mh is not None and l.get('value') is not None:
                side_home = tm(str(l['side']).split()[0]) == teams[1]
                H = float(l['value']) if side_home else -float(l['value'])
                l['grade'] = spread_grade(mh, side_home, H, odds, T)
            elif l['market'] == 'spread':
                l['grade'] = dict(status='no model', note="Your team model hasn't graded this game yet.")
            elif l['market'] in ('total', 'teamtotal'):
                l['grade'] = grade(0.5, odds, TOTAL_NOTE)
            elif l['market'] == 'moneyline' and mh is not None:
                side_home = tm(str(l['side']).split()[0]) == teams[1]
                ph = 0.5 * (1 + math.erf(mh / ML_SIGMA / math.sqrt(2)))
                p = ph if side_home else 1 - ph
                l['grade'] = grade(p, odds, f"Model lean (backtest 2016-26: betting the model's moneyline side at closing prices returned +1.2% over 1,392 bets, about break-even; the model is a bit overconfident): your team model has {teams[1] if mh >= 0 else teams[0]} by {abs(mh):.1f}, "
                                            f"so this side wins about {p * 100:.0f}% of the time (spread turned into a win chance).", model=mh)
            else:
                l['grade'] = dict(status='no model', note="Your team model hasn't graded this game yet." if l['market'] == 'moneyline' else 'No model.')
            n['lines'] += 1; n['profitable'] += l['grade'].get('status') == 'profitable'
        for o in g.get('other_props', []):
            mk = None
            if o.get('src') == 'SportsLine':
                hit = next((s for s in sl if s.get('label') == o.get('play') and s.get('expert') == o.get('expert')), None)
                mk = hit.get('market') if hit else 'UNKNOWN'
            odds = o.get('odds'); odds = float(odds) if odds not in (None, '') else None
            o['grade'] = grade_prop(P, F, bands, o.get('play', ''), odds, teams, mk)
            if odds is not None and odds < LIMIT and o['grade'].get('status') in ('profitable', 'negative'):   # Aidan, Nov 25 2026
                o['grade'].update(status='negative', over_limit=True, note="Price is worse than your -150 limit for player props. " + (o['grade'].get('note') or ''))
            try: o['bet'] = bet_fields(o, AN, teams, mk)
            except Exception as e: o['bet'] = None
            n['props'] += 1; n['profitable'] += o['grade'].get('status') == 'profitable'
    ns = drop_split(B)
    print(f'left off {ns} player props where analysts disagree', file=sys.stderr)
    nd = filter_board(B, load_experts())
    print(f'left off {nd} picks from analysts who are not profitable', file=sys.stderr)
    B['games'] = sorted(held + B.get('games', []), key=lambda g: (g.get('start', ''), g.get('game', '')))
    B['tiers'] = {k: v for k, v in T.items()}
    B['grades_note'] = ("Spreads: your weekly team model's backtested cover rates. Moneylines: your team model's spread turned into a win chance (not backtested). Totals and team totals: no model beats the closing number, so they're a coin flip at the price. "
                        "Other props: TD and milestone models calibrated on 2025-2026, at the expert's price; not backtested against prices. Player props are only shown at prices of -150 or better.")
    print(json.dumps(B, indent=1))
    print(f"graded {n['lines']} game-line picks and {n['props']} other props; {n['profitable']} profitable", file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:11])
