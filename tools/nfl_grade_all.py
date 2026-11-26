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

usage: python3 -I nfl_grade_all.py board.json an.json sl.json|- stats_prev.csv stats_cur.csv bands.json bets.csv tiers.csv [novig_offers.json] > board_graded.json
"""
import sys, os, json, re, math, unicodedata, bisect, csv

TEAMFIX = {'JAC': 'JAX', 'LAR': 'LA', 'WSH': 'WAS'}
ATD_A, ATD_B = 0.55, 0.10      # anytime-TD lambda calibration (2025-2026 walk-forward, players with lambda > 0.08)
PTD_A, PTD_B = 0.50, 0.70      # passing-TD lambda calibration (QBs, same test)
ML_SIGMA = 11.1
TOTAL_NOTE = "No model here beats the closing total (tested 2021-2026: 45-48% when it disagreed), so this is a coin flip at the posted price."


def norm(n):
    n = ''.join(c for c in unicodedata.normalize('NFD', n or '') if unicodedata.category(c) != 'Mn').lower()
    n = re.sub(r"[.'’`]", '', n); n = re.sub(r'[^a-z ]', ' ', n)
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return ' '.join(n.split())


def be(o): return 100 / (o + 100) if o > 0 else -o / (-o + 100)
def tm(t): return TEAMFIX.get(t, t)


LIMIT = -150     # Aidan, Nov 25 2026: player props only at -150 or better
WIN = 25.0       # 1 unit = to win $25 (same as nfl_pregame_v6.py)
BOOKS = {69: 'FanDuel', 75: 'BetMGM', 49: 'Caesars', 2988: 'Fanatics', 4620: 'theScore Bet'}
AN_MK = {'core_bet_type_16_receiving_yards': 'rec_yds', 'core_bet_type_12_rushing_yards': 'rush_yds',
         'core_bet_type_10_pass_completions': 'pass_cmp', 'core_bet_type_70_tackles_assists': 'tkl',
         'core_bet_type_15_receptions': 'rec', 'core_bet_type_9_passing_yards': 'pass_yds', 'core_bet_type_18_rushing_attempts': 'rush_att'}
STAT_KEY = {'receiving yards': 'rec_yds', 'rushing yards': 'rush_yds', 'pass completions': 'pass_cmp', 'tackles + assists': 'tkl',
            'receptions': 'rec', 'passing yards': 'pass_yds', 'rush attempts': 'rush_att'}


def enforce_limit(B, AN, bands, nvf):
    """Re-price yardage props whose board price is worse than LIMIT (see the module docstring). Returns (re-priced, no price)."""
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
        print('novig offers file not found: props over the -150 limit re-priced without Novig', file=sys.stderr)
    moved = gone = 0
    for g in B.get('games', []):
        for p in g.get('props', []):
            b = p.get('best')
            if not b or b.get('odds') is None or b['odds'] >= LIMIT: continue
            s = STAT_KEY.get(p.get('stat')); el = float(p['expert_line']); under = p['side'] == 'Under'; proj = p.get('model_proj')
            ok = [dict(o) for o in offers.get((g['id'], norm(p['player']), s, p['side']), [])
                  if o['odds'] >= LIMIT and (o['line'] >= el - 1.0 if under else o['line'] <= el + 1.0)]
            for o in ok:
                po = p_over(bands, s, proj, o['line']) if proj is not None else None
                o['p'] = None if po is None else (1 - po if under else po); o['edge'] = None if po is None else o['p'] - be(o['odds'])
            if not ok:
                p['best'] = None; p['price_ok'] = False; p['status'] = 'no price'; gone += 1; continue
            rated = [o for o in ok if o['edge'] is not None]
            bo = max(rated, key=lambda o: (o['edge'], o['odds'])) if rated else max(ok, key=lambda o: (o['line'] if under else -o['line'], o['odds']))
            st = round(WIN * (-bo['odds']) / 100, 2) if bo['odds'] < 0 else round(WIN * 100 / bo['odds'], 2)
            p['best'] = dict(book=bo['book'], line=bo['line'], odds=int(bo['odds']), edge=None if bo['edge'] is None else round(bo['edge'], 3),
                             p=None if bo['p'] is None else round(bo['p'], 3), stake=st)
            p['price_ok'] = True; moved += 1
            p['status'] = 'no model' if bo['edge'] is None else 'profitable' if bo['edge'] > 0 else 'negative'
        order = ['bet', 'profitable', 'negative', 'no model', 'no price']
        g.get('props', []).sort(key=lambda p: (order.index(p['status']) if p['status'] in order else 9, -((p.get('best') or {}).get('edge') or -9)))
    return moved, gone


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


def filter_board(B, E):
    if not E: return 0
    dropped = 0
    for g in B.get('games', []):
        keep = []
        for p in g.get('props', []):
            ex = [x for x in (p.get('experts') or []) if expert_ok(E, '', x)]
            if not ex: dropped += 1; continue
            if len(ex) < len(p.get('experts') or []):
                names = {re.sub(r'\s*\((Action Network|SportsLine)\)\s*$', '', x) for x in ex}
                p['why'] = [w for w in (p.get('why') or []) if str(w).split(':', 1)[0].strip() in names]
            p['experts'] = ex; p['n_experts'] = len(ex); keep.append(p)
        g['props'] = keep
        for key in ('other_props', 'lines'):
            before = len(g.get(key, []))
            g[key] = [o for o in g.get(key, []) if expert_ok(E, o.get('src'), o.get('expert'), o.get('user'))]
            dropped += before - len(g[key])
    B['experts_note'] = 'Only analysts profitable in CFB, NFL or UFC (or the three combined) are listed; see experts.json.'
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


def main(boardf, anf, slf, s1, s2, bandsf, betsf, tiersf, nvf='novig_offers.json'):
    B = json.load(open(boardf)); bands = json.load(open(bandsf))
    P, F = build([s1, s2]); T = load_tiers(tiersf)
    sl = json.load(open(slf)).get('picks', []) if slf != '-' else []
    AN = json.load(open(anf))
    B['season'], B['week'] = AN.get('season'), AN.get('week')
    M = {}
    for r in csv.DictReader(open(betsf)):
        try: M[r['matchup'].replace(' ', '')] = float(r['model_home'])
        except (ValueError, KeyError): pass
    n = dict(lines=0, props=0, profitable=0)
    moved, gone = enforce_limit(B, AN, bands, nvf)
    print(f'-150 limit: {moved} props re-priced at -150 or better, {gone} left with no price', file=sys.stderr)
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
                l['grade'] = grade(p, odds, f"Model lean, not backtested: your team model has {teams[1] if mh >= 0 else teams[0]} by {abs(mh):.1f}, "
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
    nd = filter_board(B, load_experts())
    print(f'left off {nd} picks from analysts who are not profitable', file=sys.stderr)
    B['tiers'] = {k: v for k, v in T.items()}
    B['grades_note'] = ("Spreads: your weekly team model's backtested cover rates. Moneylines: your team model's spread turned into a win chance (not backtested). Totals and team totals: no model beats the closing number, so they're a coin flip at the price. "
                        "Other props: TD and milestone models calibrated on 2025-2026, at the expert's price; not backtested against prices. Player props are only shown at prices of -150 or better.")
    print(json.dumps(B, indent=1))
    print(f"graded {n['lines']} game-line picks and {n['props']} other props; {n['profitable']} profitable", file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:10])
