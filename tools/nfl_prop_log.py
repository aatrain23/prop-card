#!/usr/bin/env python3
"""Keep the NFL player-prop analyst records current (Aidan, Nov 26 2026: "profitable betters only", then "Yes" to refreshing them weekly).

Two parts:
  log      called by tools/nfl_grade_all.py on every pre-game board run: every analyst's player-prop pick (Action Network and
           SportsLine, ALL analysts, before any filter) on the board's games goes into nfl-data/expert_props_log.csv, once per pick.
  log_lines the same for moneyline picks (stat "ml"; graded from final scores, own records in tools/nfl_ml_records.json).
  refresh  run by the Tuesday NFL grades task: grades the logged picks from nflverse stats (1 unit risked at the posted price),
           adds them to the frozen history in tools/nfl_prop_records_base.json (AN 2023 on, SportsLine 2022 on, through 2026 wk 10),
           writes tools/nfl_prop_records.json, and rebuilds experts.json / experts.js with tools/build_experts.py.

usage:
  python3 -I tools/nfl_prop_log.py refresh <stats_player_week_SEASON.csv> <play_by_play_SEASON.parquet|-> [games.csv]
"""
import csv, json, os, re, subprocess, sys, unicodedata

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LOG = os.path.join(ROOT, 'nfl-data', 'expert_props_log.csv')
BASE = os.path.join(ROOT, 'tools', 'nfl_prop_records_base.json')
ML_BASE = os.path.join(ROOT, 'tools', 'nfl_ml_records_base.json')
ML_RECS = os.path.join(ROOT, 'tools', 'nfl_ml_records.json')
GAMES_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
RECS = os.path.join(ROOT, 'tools', 'nfl_prop_records.json')
COLS = ['key', 'logged', 'start', 'away', 'home', 'src', 'expert', 'market', 'play', 'player', 'stat', 'side', 'line', 'odds',
        'actual', 'result', 'units']
AN_MK = {'receiving_yards': 'rec_yds', 'rushing_yards': 'rush_yds', 'receptions': 'rec', 'passing_yards': 'pass_yds',
         'rushing_attempts': 'rush_att', 'tackles_assists': 'tkl', 'interceptions': 'pass_int', 'passing_attempts': 'pass_att',
         'passing_tds': 'pass_tds', 'pass_completions': 'pass_cmp', 'rushing_receiving_yards': 'rr_yds',
         'passing_rushing_yards': 'pr_yds', 'longest_reception': 'long_rec', 'longest_rush': 'long_rush',
         'longest_completion': 'long_cmp', 'sacks': 'sacks', 'field_goals_made': 'fg', 'extra_points_made': 'pat',
         'kicking_points': 'kick_pts'}
MILE = {'receiving_yards': 'rec_yds', 'receptions': 'rec', 'rushing_yards': 'rush_yds', 'passing_yards': 'pass_yds',
        'passing_touchdowns': 'pass_tds', 'rushing_attempts': 'rush_att', 'passing_attempts': 'pass_att', 'sacks': 'sacks', 'tackles': 'tkl'}
SL_MK = {'TOTAL_RECEIVING_YARDS': 'rec_yds', 'TOTAL_RUSHING_YARDS': 'rush_yds', 'TOTAL_RECEPTIONS': 'rec', 'TOTAL_PASSING_YARDS': 'pass_yds',
         'TOTAL_CARRIES': 'rush_att', 'TOTAL_RUSHING_RECEIVING_YARDS': 'rr_yds', 'TOTAL_TACKLES_PLUS_ASSISTS': 'tkl', 'TOTAL_TACKLES': 'tkl',
         'TOTAL_PASSING_TOUCHDOWNS': 'pass_tds', 'TOTAL_PASSING_ATTEMPTS': 'pass_att', 'TOTAL_PASSING_INTERCEPTIONS': 'pass_int',
         'TOTAL_PASSING_COMPLETIONS': 'pass_cmp', 'LONGEST_RECEPTION': 'long_rec', 'LONGEST_RUSH': 'long_rush',
         'LONGEST_PASSING_COMPLETION': 'long_cmp', 'TOTAL_MADE_FIELD_GOALS': 'fg', 'TOTAL_SACKS': 'sacks',
         'TOTAL_PASSING_PLUS_RUSHING_YARDS': 'pr_yds', 'TOTAL_KICKING_POINTS': 'kick_pts', 'TOTAL_MADE_EXTRA_POINTS': 'pat'}
SL_FIXED = {'ANYTIME_TOUCHDOWN_SCORER': ('td', 0.5), 'PLAYER_TO_SCORE_2_OR_MORE_TOUCHDOWNS': ('td', 1.5), 'TO_THROW_AN_INTERCEPTION': ('pass_int', 0.5)}
NOT_PROPS = ('team_score', 'free_form', 'betsync_unsupported')
TEAM = {'JAC': 'JAX', 'LAR': 'LA', 'WSH': 'WAS'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[.'’`]", '', s); s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    return re.sub(r'[^a-z]', '', s)


def short_key(full):
    p = re.sub(r"[.'’`]", '', unicodedata.normalize('NFKD', str(full or '')).encode('ascii', 'ignore').decode())
    p = re.sub(r'\b(Jr|Sr|II|III|IV|V)\b', '', p).split()
    return (p[0][0] + ''.join(p[1:])).lower() if len(p) > 1 else norm(full)


def an_market(cpt, play):
    c = re.sub(r'^core_bet_type_\d+_(\d+_)?', '', cpt or '')
    yes = not re.search(r'\bNo\b', play or '')
    if c in NOT_PROPS: return None
    if c == 'anytime_touchdown_scorer': return ('td', 0.5, 'Over' if yes else 'Under')
    m = re.match(r'to_score_(\d+)_or_more_touchdowns$', c)
    if m: return ('td', int(m.group(1)) - 0.5, 'Over' if yes else 'Under')
    m = re.match(r'player_(\w+?)_milestones_(\d+)_or_more$', c)
    if m and m.group(1) in MILE: return (MILE[m.group(1)], int(m.group(2)) - 0.5, 'Over' if yes else 'Under')
    if c in AN_MK: return (AN_MK[c], None, None)
    return ('', None, None)   # a prop market this log can't grade (first TD scorer etc.): logged, not counted


# ---------------- log (called from nfl_grade_all.py)
def log_picks(AN, sl, games):
    """games: the board's games (dicts with away, home, start). Appends new picks; returns how many were added."""
    rows = list(csv.DictReader(open(LOG))) if os.path.exists(LOG) else []
    have = {r['key'] for r in rows}
    want = {(TEAM.get(g.get('away'), g.get('away')), TEAM.get(g.get('home'), g.get('home'))): g.get('start', '') for g in games}
    T = AN.get('teams', {}); PL = AN.get('players', {}); G = AN.get('games', {})
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    new = []
    for pk in AN.get('picks', []):
        pid, eid, ename, cpt, play, side, val, odds, plid, gid, created, res, note = (list(pk) + [''] * 13)[:13]
        g = G.get(str(gid))
        if not g: continue
        away, home = TEAM.get(T.get(str(g[1]), ''), T.get(str(g[1]), '')), TEAM.get(T.get(str(g[2]), ''), T.get(str(g[2]), ''))
        if (away, home) not in want: continue
        mk = an_market(cpt, play)
        if mk is None: continue
        stat, fixed, fside = mk
        line = fixed if fixed is not None else val
        sd = fside or (side if side in ('Over', 'Under') else '')
        pl = PL.get(str(plid)) or []
        key = f'AN{pid}'
        if key in have: continue
        have.add(key)
        new.append(dict(key=key, logged=now, start=g[0], away=away, home=home, src='Action Network', expert=ename, market=cpt, play=play,
                        player=pl[0] if pl else re.sub(r'\s[ou]\d.*$', '', play or ''), stat=stat, side=sd, line=line, odds=odds))
    for p in sl:
        away, home = TEAM.get(p.get('away'), p.get('away')), TEAM.get(p.get('home'), p.get('home'))
        if (away, home) not in want: continue
        mkt = p.get('market') or ''
        if mkt in SL_FIXED: stat, line = SL_FIXED[mkt]
        elif mkt in SL_MK: stat, line = SL_MK[mkt], p.get('value')
        elif not mkt: continue
        else: stat, line = '', p.get('value')
        sd = {'OVER': 'Over', 'UNDER': 'Under', 'YES': 'Over', 'NO': 'Under'}.get(str(p.get('side') or '').upper(), '')
        m = re.match(r'^(.+?)\s(?:Over|Under|Yes|No)\b', p.get('label') or '', re.I) or re.match(r'^(.+?)\s[+-]\d+$', p.get('label') or '')
        key = 'SL' + str(p.get('id') or f"{p.get('expert')}|{p.get('label')}|{away}@{home}")
        if key in have: continue
        have.add(key)
        new.append(dict(key=key, logged=now, start=want[(away, home)], away=away, home=home, src='SportsLine', expert=p.get('expert', ''),
                        market=mkt, play=p.get('label', ''), player=m.group(1) if m else '', stat=stat, side=sd, line=line, odds=p.get('odds')))
    if not new: return 0
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    first = not os.path.exists(LOG)
    with open(LOG, 'a', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if first: w.writeheader()
        for r in new: w.writerow({k: r.get(k, '') for k in COLS})
    return len(new)


def log_lines(games):
    """Moneyline picks on the board's games (all analysts, before any filter), into the same log with stat 'ml' (Nov 26 2026)."""
    import datetime
    rows = list(csv.DictReader(open(LOG, encoding='utf-8'))) if os.path.exists(LOG) else []
    have = {r['key'] for r in rows}
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    new = []
    for g in games:
        away, home = TEAM.get(g.get('away'), g.get('away')), TEAM.get(g.get('home'), g.get('home'))
        for l in g.get('lines', []):
            if l.get('market') != 'moneyline' or not l.get('side'): continue
            side = str(l['side']).split()[0]; side = TEAM.get(side, side)
            key = f"ML|{l.get('src')}|{l.get('expert')}|{away}@{home}|{str(g.get('start', ''))[:10]}|{side}"
            if key in have: continue
            have.add(key)
            new.append(dict(key=key, logged=now, start=g.get('start', ''), away=away, home=home, src=l.get('src', ''), expert=l.get('expert', ''),
                            market='moneyline', play=l.get('play', ''), player=l.get('user', ''), stat='ml', side=side, line='', odds=l.get('odds')))
    if not new: return 0
    first = not os.path.exists(LOG)
    with open(LOG, 'a', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if first: w.writeheader()
        for r in new: w.writerow({k: r.get(k, '') for k in COLS})
    return len(new)


# ---------------- refresh (Tuesday)
def refresh(statsf, pbpf='-'):
    import pandas as pd
    rows = list(csv.DictReader(open(LOG, encoding='utf-8'))) if os.path.exists(LOG) else []
    st = pd.read_csv(statsf, low_memory=False)
    st = st[st.season_type.isin(['REG', 'POST'])].copy()
    num = ['passing_yards', 'passing_tds', 'completions', 'attempts', 'passing_interceptions', 'rushing_yards', 'carries', 'receiving_yards',
           'receptions', 'rushing_tds', 'receiving_tds', 'def_tackles_solo', 'def_tackle_assists', 'def_tackles_with_assist', 'def_sacks',
           'fg_made', 'pat_made']
    for c in num: st[c] = pd.to_numeric(st.get(c), errors='coerce').fillna(0)
    S = dict(pass_yds=st.passing_yards, pass_tds=st.passing_tds, pass_cmp=st.completions, pass_att=st.attempts, pass_int=st.passing_interceptions,
             rush_yds=st.rushing_yards, rush_att=st.carries, rec_yds=st.receiving_yards, rec=st.receptions,
             tkl=st.def_tackles_solo + st.def_tackle_assists + st.def_tackles_with_assist, rr_yds=st.rushing_yards + st.receiving_yards,
             pr_yds=st.passing_yards + st.rushing_yards, td=st.rushing_tds + st.receiving_tds, sacks=st.def_sacks, fg=st.fg_made,
             pat=st.pat_made, kick_pts=3 * st.fg_made + st.pat_made)
    for k, v in S.items(): st[k] = v
    if pbpf not in ('-', '') and os.path.exists(pbpf):
        pb = pd.read_parquet(pbpf, columns=['game_id', 'complete_pass', 'yards_gained', 'receiver_player_id', 'passer_player_id',
                                            'rusher_player_id', 'rush_attempt', 'two_point_attempt'])
        cp = pb[pb.complete_pass == 1]
        for col, who, src in (('long_rec', 'receiver_player_id', cp), ('long_cmp', 'passer_player_id', cp),
                              ('long_rush', 'rusher_player_id', pb[(pb.rush_attempt == 1) & (pb.two_point_attempt != 1)])):
            x = src.groupby(['game_id', who]).yards_gained.max().rename(col).reset_index().rename(columns={who: 'player_id'})
            st = st.merge(x, on=['game_id', 'player_id'], how='left'); st[col] = st[col].fillna(0)
    st['team'] = st.team.replace(TEAM); st['opponent_team'] = st.opponent_team.replace(TEAM)
    idx = {}
    for r in st.itertuples(index=False):
        g = (r.team, r.opponent_team)
        for k in {norm(r.player_display_name), short_key(r.player_display_name), norm(r.player_name)}:
            idx.setdefault((k, g), []).append(r)
    posted = set(zip(st.team, st.opponent_team))
    pay = lambda o: o / 100 if o > 0 else 100 / -o
    graded = 0
    for r in rows:
        if r.get('result') or not r.get('stat') or r.get('side') not in ('Over', 'Under'): continue
        try: line, odds = float(r['line']), float(r['odds'])
        except (TypeError, ValueError): continue
        if not odds: continue
        hits = []
        for g in ((r['away'], r['home']), (r['home'], r['away'])):
            if g not in posted: continue
            for k in {norm(r['player']), short_key(r['player'])}:
                hits += idx.get((k, g), [])
        if not any(g in posted for g in ((r['away'], r['home']), (r['home'], r['away']))): continue   # game not in the stats yet
        ids = {h.player_id for h in hits}
        if len(ids) > 1: continue
        if not hits: r.update(actual='DNP', result='Void', units='0'); graded += 1; continue   # no stats row: didn't play
        a = getattr(hits[0], r['stat'], None)
        if a is None: continue
        a = float(a)
        res = 'Push' if a == line else ('Win' if (a > line) == (r['side'] == 'Over') else 'Loss')
        r.update(actual=f'{a:g}', result=res, units=f"{pay(odds) if res == 'Win' else -1.0 if res == 'Loss' else 0.0:.3f}"); graded += 1
    # moneylines: final scores from nflverse games.csv (a tie is a push)
    try:
        import io, urllib.request
        G = list(csv.DictReader(io.StringIO(urllib.request.urlopen(GAMES_URL, timeout=60).read().decode())))
        fin = {}
        for g in G:
            if g.get('away_score') in ('', None) or g.get('home_score') in ('', None): continue
            a, h = TEAM.get(g['away_team'], g['away_team']), TEAM.get(g['home_team'], g['home_team'])
            fin[(a, h, g['gameday'])] = (float(g['away_score']), float(g['home_score']))
        import datetime
        for r in rows:
            if r.get('result') or r.get('stat') != 'ml': continue
            try: odds = float(r['odds'])
            except (TypeError, ValueError): continue
            d0 = datetime.datetime.fromisoformat(r['start'].replace('Z', '+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=-5))).date()
            sc = next((fin[k] for k in ((r['away'], r['home'], str(d0)), (r['away'], r['home'], str(d0 - datetime.timedelta(days=1)))) if k in fin), None)
            if not sc: continue
            mine = sc[0] if r['side'] == r['away'] else sc[1] if r['side'] == r['home'] else None
            if mine is None: continue
            theirs = sc[1] if r['side'] == r['away'] else sc[0]
            res = 'Push' if mine == theirs else ('Win' if mine > theirs else 'Loss')
            r.update(actual=f'{sc[0]:g}-{sc[1]:g}', result=res, units=f"{pay(odds) if res == 'Win' else -1.0 if res == 'Loss' else 0.0:.3f}"); graded += 1
    except Exception as e:
        print(f'moneyline grading skipped ({e})', file=sys.stderr)
    with open(LOG, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader()
        for r in rows: w.writerow({k: r.get(k, '') for k in COLS})
    base = json.load(open(BASE))
    rec = {s: {n: list(v) for n, v in base[s].items()} for s in ('an', 'sl')}
    last = ''
    mlb = json.load(open(ML_BASE))
    mrec = {k: {n: list(v) for n, v in mlb[k].items()} for k in ('an', 'sl')}; musers = dict(mlb.get('an_users', {})); mlast = ''
    for r in rows:
        if r.get('stat') != 'ml' or r.get('result') not in ('Win', 'Loss', 'Push'): continue
        if r['start'][:10] <= mlb['through']: continue   # already in the base history
        s = 'an' if r['src'] == 'Action Network' else 'sl'
        v = mrec[s].setdefault(r['expert'].strip(), [0, 0, 0, 0.0])
        v[{'Win': 0, 'Loss': 1, 'Push': 2}[r['result']]] += 1; v[3] = round(v[3] + float(r['units']), 2)
        if s == 'an' and r.get('player'): musers.setdefault(r['player'].lower(), r['expert'].strip())
        mlast = max(mlast, r['start'][:10])
    json.dump({'through': f"{mlb['through']} + logged board picks to {mlast}" if mlast else mlb['through'], 'an': mrec['an'], 'sl': mrec['sl'], 'an_users': musers},
              open(ML_RECS, 'w'), ensure_ascii=False, indent=0)
    for r in rows:
        if r.get('stat') == 'ml' or r.get('result') not in ('Win', 'Loss', 'Push'): continue
        s = 'an' if r['src'] == 'Action Network' else 'sl'
        v = rec[s].setdefault(r['expert'].strip(), [0, 0, 0, 0.0])
        v[{'Win': 0, 'Loss': 1, 'Push': 2}[r['result']]] += 1; v[3] = round(v[3] + float(r['units']), 2)
        last = max(last, r['start'][:10])
    out = {'through': f"{base['through']} + logged board picks to {last}" if last else base['through'], 'an': rec['an'], 'sl': rec['sl']}
    json.dump(out, open(RECS, 'w'), ensure_ascii=False, indent=0)
    p = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'tools', 'build_experts.py'), os.path.join(ROOT, 'tools', 'experts_raw.json'),
                        os.path.join(ROOT, 'experts.json'), RECS, ML_RECS], capture_output=True, text=True)
    if p.returncode: sys.exit('build_experts.py failed: ' + p.stderr[-500:])
    E = json.load(open(os.path.join(ROOT, 'experts.json')))['nflprop']
    keep = {s: sorted(v['name'] for v in E[s].values() if v['ok']) for s in ('an', 'sl')}
    EM = json.load(open(os.path.join(ROOT, 'experts.json')))['nflml']
    keep_ml = sorted(v['name'] for s in ('an', 'sl') for v in EM[s].values() if v['ok'])
    print(json.dumps(dict(graded_now=graded, logged=len(rows), still_open=sum(not r.get('result') for r in rows), through=out['through'],
                          profitable_an=len(keep['an']), profitable_sl=len(keep['sl']), keep=keep,
                          moneyline_list=keep_ml), indent=1))


if __name__ == '__main__':
    if sys.argv[1] == 'refresh': refresh(*sys.argv[2:4])
    else: sys.exit(__doc__)
