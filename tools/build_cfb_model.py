"""Rebuild cfb_model.json (read by lines.html, the Line Shop) from a CFB Team Grades model run.

Usage: python3 -I tools/build_cfb_model.py WORKDIR cfb_model.json [--tuesday]

WORKDIR is the folder the weekly model ran in (holds cfb_lines.csv, cfb_bets.csv,
cfb_totals.csv and sl.txt). With --tuesday, this run's market lines become the
"Tuesday" reference lines (tue_home, tue_total); otherwise the Tuesday lines already
in cfb_model.json are kept, game by game.
"""
import json, sys, datetime
import pandas as pd

D, OUT = sys.argv[1], sys.argv[2]
TUE = '--tuesday' in sys.argv[3:]

try:
    old = json.load(open(OUT))
except FileNotFoundError:
    old = {'games': []}
O = {(g['away'], g['home']): g for g in old.get('games', [])}

L = pd.read_csv(f'{D}/cfb_lines.csv')
B = pd.read_csv(f'{D}/cfb_bets.csv').set_index('matchup')
T = pd.read_csv(f'{D}/cfb_totals.csv').set_index('matchup')
S = pd.read_csv(f'{D}/sl.txt', sep='|', names=['away', 'home', 'pa', 'ph', 'ou', 'hl', 'slg', 'slpick']).set_index(['away', 'home'])


def home_val(s, home):
    """'Michigan +3.5' -> 3.5 (home spread, negative = home favored)."""
    r = str(s)[len(home):].strip()
    return 0.0 if r == 'PK' else float(r)


def num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


games = []
for r in L.itertuples():
    k = (r.away, r.home)
    o = O.get(k, {})
    s = S.loc[k] if k in S.index else None
    wx = T.loc[r.matchup, 'weather'] if r.matchup in T.index else ''
    wx = '' if wx != wx else str(wx)
    games.append(dict(
        away=r.away, home=r.home,
        grade=B.loc[r.matchup, 'grade'] if r.matchup in B.index else None,
        model_home=home_val(r.model_spread, r.home),
        sl_home=round(-(float(s.ph) - float(s.pa)), 1) if s is not None else None,
        tue_home=home_val(r.spread, r.home) if TUE else o.get('tue_home'),
        model_total=num(r.model_total),
        sl_total=float(s.pa) + float(s.ph) if s is not None else None,
        tue_total=num(r.total) if TUE else o.get('tue_total'),
        total_grade=T.loc[r.matchup, 'grade'] if r.matchup in T.index else None,
        weather=wx or o.get('weather', '') or '',
    ))

today = datetime.date.today().isoformat()
args = sys.argv[3:]
week = int(args[args.index('--week') + 1]) if '--week' in args else old.get('week')
out = {
    'source': f'CFB Team Grades (https://claude.ai/artifact/SzBTNvffYWB7d22EaNiCXX), {"Tuesday" if TUE else "update"} run of {today}',
    'week': week,
    'updated': today,
    'games': games,
}
json.dump(out, open(OUT, 'w'), indent=1, ensure_ascii=False)
print(len(games), 'games written;', sum(g['tue_home'] is None for g in games), 'without a Tuesday line')
