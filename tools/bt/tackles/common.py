import pandas as pd, numpy as np, re
nm = lambda s: re.sub(r'[^a-z]', '', str(s).lower())
def load():
    d = pd.read_parquet('data/tkl.parquet'); d['key'] = d.player_name.map(nm)
    a = pd.concat([pd.read_csv('data/an_picks.csv'), pd.read_csv('data/sl_picks.csv')])
    t = a[a.stat == 'Tackles+assists'].copy()
    t['name'] = t.play.str.extract(r'^(.+?)\s[ou]\s?\d')[0]; t['key'] = t.name.map(nm)
    L = {}
    for r in d.itertuples(): L.setdefault((r.season, r.week, r.team, r.key), []).append(r.Index)
    t['row'] = [(lambda c: c[0] if len(c) == 1 else -1)(L.get((r.season, r.week, r.away, r.key), []) + L.get((r.season, r.week, r.home, r.key), [])) for r in t.itertuples()]
    t = t[(t.row >= 0) & t.result.isin(['win', 'loss', 'push'])].reset_index(drop=True)
    return d, t
