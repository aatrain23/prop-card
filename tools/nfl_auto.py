#!/usr/bin/env python3
"""Automatic NFL Team Grades refresh, run by .github/workflows/nfl-grades.yml.

  nfl_auto.py check   -> prints run=true/false (and writes it to $GITHUB_OUTPUT): true when nflverse has published a new
                         injury report or weekly roster file, or the saved Madden ratings changed, since the last refresh, or once a day after 9 AM ET (line moves)
  nfl_auto.py run     -> reruns the model (nfl-data/madden/nfl_weekly.py) and rewrites nfl-data/ grades, bets, tiers,
                         seasons, summary, inputs, totals, home field and meta.json, plus nfl_model.json (Line Shop). In bet_log.csv it regrades this week's unplayed entries and grades finished ones
                         but never adds a bet (the Tuesday and Sunday Claude runs do that). It never touches pregame.json or the Madden files.
State is kept in nfl-data/auto_state.json.
"""
import sys, os, json, shutil, subprocess, tempfile, datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ND = os.path.join(ROOT, 'nfl-data')
STATE = os.path.join(ND, 'auto_state.json')
ET = ZoneInfo('America/New_York')
BU = 'https://github.com/nflverse/nflverse-data/releases/download/'
OUT = {'grades': 'nfl_grades.csv', 'bets': 'nfl_bets.csv', 'bet_log': 'nfl_bet_log.csv', 'tiers': 'nfl_tiers.csv', 'seasons': 'nfl_seasons.csv',
       'summary': 'nfl_summary.csv', 'inputs': 'nfl_inputs.csv', 'totals': 'nfl_totals.csv', 'total_tiers': 'nfl_total_tiers.csv',
       'total_summary': 'nfl_total_summary.csv', 'hfa': 'nfl_hfa.csv', 'hfa_seasons': 'nfl_hfa_seasons.csv'}


def season(now):
    return now.year if now.month >= 8 else now.year - 1


def last_modified(url):
    try:
        r = subprocess.run(['curl', '-sIL', '--max-time', '30', url], capture_output=True, text=True).stdout
    except Exception:
        return ''
    v = [l.split(':', 1)[1].strip() for l in r.splitlines() if l.lower().startswith('last-modified:')]
    return v[-1] if v else ''


def madden_iteration():
    try:
        import csv
        r = csv.DictReader(open(os.path.join(ND, 'madden', 'current.csv'))); return next(r)['iteration']
    except Exception:
        return ''


def signature(now):
    s = season(now)
    return {'injuries': last_modified(f'{BU}injuries/injuries_{s}.parquet'),
            'rosters': last_modified(f'{BU}weekly_rosters/roster_weekly_{s}.parquet'),
            'madden': madden_iteration()}


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def decide(now, sig, st):
    why = []
    names = {'injuries': 'injury report', 'rosters': 'roster file', 'madden': 'Madden ratings'}
    for k in names:
        if sig[k] and sig[k] != st.get(k):
            why.append('new ' + names[k])
    if st.get('day') != now.strftime('%Y-%m-%d') and now.hour >= 9:
        why.append('daily refresh')
    return why


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'check'
    now = datetime.datetime.now(ET)
    sig = signature(now); st = load(); why = decide(now, sig, st)
    if mode == 'check':
        print('run=' + ('true' if why else 'false'), '|', ', '.join(why) or 'nothing new', '|', sig)
        if os.environ.get('GITHUB_OUTPUT'):
            open(os.environ['GITHUB_OUTPUT'], 'a').write('run=' + ('true' if why else 'false') + '\n')
        return
    if not why and '--force' not in sys.argv:
        print('nothing new'); return
    wd = tempfile.mkdtemp(prefix='nfl_auto_')
    shutil.copy(os.path.join(ND, 'madden', 'launch.csv'), os.path.join(wd, 'madden_launch.csv'))
    shutil.copy(os.path.join(ND, 'madden', 'current.csv'), os.path.join(wd, 'madden_current.csv'))
    shutil.copy(os.path.join(ND, 'bet_log.csv'), os.path.join(wd, 'nfl_bet_log.csv'))
    env = dict(os.environ, TZ='America/New_York', NFL_NO_NEW_BETS='1')
    r = subprocess.run([sys.executable, os.path.join(ND, 'madden', 'nfl_weekly.py'), wd], capture_output=True, text=True, env=env)
    new = dict(st, day=now.strftime('%Y-%m-%d'))
    for k in ('injuries', 'rosters', 'madden'):
        if sig[k]: new[k] = sig[k]
    if r.returncode:
        tail = (r.stdout + r.stderr)[-1500:]
        if 'No games left this season' in tail:
            print('No games left this season: nothing to update')
            json.dump(new, open(STATE, 'w')); return
        print(tail); raise SystemExit('model run failed')
    import csv
    rows = {k: list(csv.reader(open(os.path.join(wd, f)))) for k, f in OUT.items()}
    if len(rows['grades']) != 33: raise SystemExit('grades file does not have 32 teams')
    for k, f in OUT.items():
        if not os.path.exists(os.path.join(ND, k + '.csv')): continue
        old = open(os.path.join(ND, k + '.csv')).readline().strip(); nw = open(os.path.join(wd, f)).readline().strip()
        if old != nw: raise SystemExit(f'{k}.csv header changed: not copied')
    for k, f in OUT.items(): shutil.copy(os.path.join(wd, f), os.path.join(ND, k + '.csv'))
    mj = json.load(open(os.path.join(wd, 'nfl_model.json')))        # this week's games for the Line Shop (spread, total, home field)
    if mj.get('games'): json.dump(mj, open(os.path.join(ROOT, 'nfl_model.json'), 'w'), indent=1)
    meta = json.load(open(os.path.join(ND, 'meta.json')))
    wk = rows['bets'][1][0] if len(rows['bets']) > 1 else None
    if wk: meta['label'] = f'Week {wk} grades'
    meta['run'] = now.strftime('%a %b ') + str(now.day) + now.strftime(' %Y, ') + now.strftime('%I:%M %p').lstrip('0') + ' ET, automatic: ' + ', '.join(why or ['forced'])
    json.dump(meta, open(os.path.join(ND, 'meta.json'), 'w'))
    new['last_run'] = now.isoformat(timespec='seconds'); new['why'] = why
    json.dump(new, open(STATE, 'w'))
    print('updated:', meta['run'])
    print(open(os.path.join(wd, 'madden_status.txt')).read().strip())


if __name__ == '__main__':
    main()
