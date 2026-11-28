"""Discord alerts for games Aidan has bet (Nov 27 2026): every scoring play and every final in a game on his College football
or NFL bet card, with how each of his bets on that game stands. Reads the cards' published feed sheets and ESPN's public
scoreboard; posts to the Discord webhook in the DISCORD_WEBHOOK secret. Run every 5 minutes by .github/workflows/bet-alerts.yml.

usage: python3 tools/bet_alerts.py <state.json in> <state.json out>"""
import csv, io, json, math, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime, timezone, timedelta

CFB_FEED = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTHqNMre3mm5QcYdwBR4BrFavVzSPaDZUKKXdq4L_pLrgsXylKwTUm3dRDG7Iehzl7Moy2V6QTfaxIq/pub?output=csv'
NFL_FEED = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vRFDjXnJ_DHrTGWyx9-s4oyjqhQHyQ2ZCoBw_Iwkm2ZP2RylC5r2nt_t9eIWGHy7rTfx0FFplBZOcb2/pub?gid=0&single=true&output=csv'
ESPN = {'cfb': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football',
        'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'}
ET = timezone(timedelta(hours=-5))
ALIAS = {'app state': 'appalachian state', 'ul monroe': 'louisiana monroe', 'florida international': 'fiu', 'uconn': 'connecticut',
         'umass': 'massachusetts', 'sam houston': 'sam houston state', 'miami oh': 'miami ohio'}
NFL_AB = {'LA': 'LAR', 'WAS': 'WSH', 'JAC': 'JAX'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '').lower())
    s = ''.join(c for c in s if not unicodedata.combining(c)).replace('&', ' and ')
    return re.sub(r'\s+', ' ', re.sub(r"[^a-z0-9 ]", ' ', re.sub(r"['’.]", '', s))).strip()


def get(url, js=True):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (bet-alerts)'})
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
                return json.loads(b) if js else b.decode('utf-8')
        except Exception:
            if i == 2: raise
            time.sleep(3)


def team_match(t, name, sport):
    """t: an ESPN competitor's team; name: as the bet card writes it (CFB full school name, NFL abbreviation)."""
    n = norm(name)
    if sport == 'nfl':
        ab = NFL_AB.get(name.strip().upper(), name.strip().upper())
        return t.get('abbreviation', '').upper() == ab
    a = ALIAS.get(n)
    cands = [norm(t.get(k)) for k in ('location', 'displayName', 'shortDisplayName', 'abbreviation', 'name') if t.get(k)]
    return any(x == n or (a and x == a) for x in cands) or norm(t.get('displayName')).startswith(n + ' ')


def team_score(t, name, sport):
    # 2 = exact name, 1 = only the start of the full name ("Texas" vs "Texas A&M Aggies"), 0 = no match
    if not team_match(t, name, sport): return 0
    if sport == 'nfl': return 2
    n = norm(name); a = ALIAS.get(n)
    cands = [norm(t.get(k)) for k in ('location', 'displayName', 'shortDisplayName', 'abbreviation', 'name') if t.get(k)]
    return 2 if any(x == n or (a and x == a) for x in cands) else 1


def side_of(ev, name, sport):
    # which team in this game the name means, by the better match (so "Texas" is Texas, not Texas A&M)
    sa, sh = team_score(ev['away']['team'], name, sport), team_score(ev['home']['team'], name, sport)
    return None if not (sa or sh) else 'away' if sa >= sh else 'home'


def post(hook, text):
    if hook == 'dry':   # test run: print instead of posting
        print('----\n' + text); return True
    data = json.dumps({'content': text[:1990], 'allowed_mentions': {'parse': []}}).encode()
    req = urllib.request.Request(hook, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'bet-alerts (prop-card, 1.0)'})
    for i in range(3):
        try:
            urllib.request.urlopen(req, timeout=30).read(); return True
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(float(json.loads(e.read() or b'{}').get('retry_after', 2)) + .5); continue
            print('discord error', e.code); return False
        except Exception as e:
            print('discord error', e); time.sleep(2)
    return False




# ---------------------------------------------------------------------------------------------------------------------------
# Which alerts (Aidan's answers, Nov 27 2026):
#   spread / moneyline   every score, and the final
#   game total           every score, one ping when it goes over the line; no final if that ping went out
#   team total           that team's scores, one ping when it passes the line; no final if that ping went out
#   anytime TD prop      when the player scores, and the result at the final
#   other player props   one ping when the stat clears the line (or busts an under), and the result at the final
#   parlays              every score in a game with a leg in it, and each leg's result when its game ends
#   1H / 1Q bets & legs  scores during that half / quarter only, and the result when it ends
#   one score that touches several bets comes as one message listing each bet
# ---------------------------------------------------------------------------------------------------------------------------
PER_RE = r'^(1H|1Q|2H)\s+'
LEG_RE = re.compile(r'^(?:(1H|1Q|2H)\s+)?(.+?)\s+(ML|[+-]\d+(?:\.\d+)?)$')
ICON = {'W': '✅', 'L': '❌', 'P': '➖'}


def fnum(x):
    try: return float(str(x).replace('+', ''))
    except (TypeError, ValueError): return None


def load_bets():
    """[(sport, away, home, bet)]. bet: {key, text, type (Spread|Moneyline|Total|Team Total|Parlay|Prop), per ('', 1H, 1Q), side, line, ou, player, stat}"""
    out = []
    try:
        for r in csv.DictReader(io.StringIO(get(CFB_FEED, js=False))):
            mu, txt = (r.get('matchup') or '').strip(), (r.get('bet') or '').strip()
            if not mu or not txt or (r.get('result') or '').strip() or (r.get('alerts') or '').strip().lower() == 'off': continue   # bell off on the card
            typ = (r.get('type') or '').strip()
            per = (re.match(PER_RE, typ) or re.match(PER_RE, txt) or [None, ''])[1] if not txt.startswith('Parlay') else ''
            base = re.sub(PER_RE, '', typ)
            multi = ' + ' in mu or typ.startswith('Parlay') or txt.startswith('Parlay')
            if multi: base = 'Parlay'
            elif base not in ('Spread', 'Moneyline', 'Total', 'Team Total'):
                base = 'Moneyline' if re.search(r'\bML\b', txt) else 'Total' if re.match(r'^(Over|Under)\b', re.sub(PER_RE, '', txt)) else 'Spread'
            for part in mu.split(' + '):
                m = re.match(r'^(.*?) (?:at|vs\.?) (.*)$', part.strip())
                if not m: continue
                out.append(('cfb', m.group(1), m.group(2), {'key': 'cfb|' + mu + '|' + txt, 'text': txt, 'type': base, 'per': per, 'side': r.get('side') or '',
                            'line': r.get('line') or '', 'ou': 'under' if re.search(r'\bunder\b', txt, re.I) else 'over', 'player': '', 'stat': ''}))
    except Exception as e:
        print('CFB feed failed', e)
    try:
        for r in csv.DictReader(io.StringIO(get(NFL_FEED, js=False))):
            gm = (r.get('game') or '').strip()
            if not gm or (r.get('result') or '').strip() or (r.get('alerts') or '').strip().lower() == 'off': continue
            m = re.match(r'^(\S+) @ (\S+)$', gm)
            if not m: continue
            stat, player, side, line = (r.get('stat') or '').strip(), (r.get('player') or '').strip(), (r.get('side') or '').strip(), (r.get('line') or '').strip()
            typ = {'Moneyline': 'Moneyline', 'Total': 'Total', 'Spread': 'Spread', 'Team Total': 'Team Total'}.get(stat, 'Prop')
            if typ == 'Prop': txt = f"{player} {side} {line} {stat}".replace('Over 0.5 Anytime TD', 'anytime TD')
            elif typ == 'Total': txt = f"{side} {line}"
            else: txt = player
            out.append(('nfl', m.group(1), m.group(2), {'key': f"nfl|{r.get('date')}|{player}|{side}|{stat}", 'text': txt.strip(), 'type': typ, 'per': '',
                        'side': (r.get('team') or side) if typ in ('Moneyline', 'Spread', 'Team Total') else side, 'line': line,
                        'ou': side.lower() if side.lower() in ('over', 'under') else 'over', 'player': player if typ == 'Prop' else '', 'stat': stat}))
    except Exception as e:
        print('NFL feed failed', e)
    return out


def is_atd(b): return b['type'] == 'Prop' and str(b.get('stat', '')).lower().startswith('anytime')


def scored_by(name, text):
    nm = norm(name).split()
    return bool(nm) and nm[-1] in norm(text).split()


def in_window(per, period):   # is this period inside the bet's half / quarter?
    return not per or (per == '1H' and period <= 2) or (per == '1Q' and period <= 1) or (per == '2H' and period >= 3)


def game_status(typ, side_pts, opp_pts, total, ln, over, team_pts=None):
    """('W'|'L'|'P', text) for a spread / ML / total / team total at these points (side_pts / opp_pts from the bet team's side)."""
    if typ in ('Spread', 'Moneyline'):
        d = side_pts - opp_pts; c = d + (ln or 0) if typ == 'Spread' else d
        r = 'W' if c > 0 else 'L' if c < 0 else 'P'
        if typ == 'Moneyline': return r, (f"winning by {c:g}" if c > 0 else f"down {-c:g}" if c < 0 else 'tied')
        return r, (f"covering by {c:g}" if c > 0 else f"short by {-c:g}" if c < 0 else 'on the number')
    t = total if typ == 'Total' else team_pts
    if t is None or ln is None: return None, ''
    c = (t - ln) if over else (ln - t)
    r = 'W' if c > 0 else 'L' if c < 0 else 'P'
    lbl = 'total' if typ == 'Total' else 'team points'
    if over: return r, (f"{t:g} {lbl}, over by {t - ln:g}" if t > ln else f"{t:g} {lbl}, needs {math.floor(ln - t) + 1} more")
    return r, (f"{t:g} {lbl}, {ln - t:g} under" if t < ln else f"{t:g} {lbl}, over by {t - ln:g}")


def legs_here(b, ev, sport):
    """parlay legs in this game: [(text, per, typ, team, line)]"""
    out = []
    for leg in re.sub(r'^Parlay:\s*', '', b['text']).split(' + '):
        m = LEG_RE.match(leg.strip())
        if m and side_of(ev, m.group(2), sport):
            out.append((leg.strip(), m.group(1) or '', 'Moneyline' if m.group(3) == 'ML' else 'Spread', m.group(2), None if m.group(3) == 'ML' else fnum(m.group(3))))
    return out


def stand(typ, team, ln, over, ev, sport, a_pts, h_pts):
    """status of a game bet (or leg) at away / home points"""
    if typ == 'Total': return game_status('Total', 0, 0, a_pts + h_pts, ln, over)
    w = side_of(ev, team, sport)
    if not w: return None, ''
    me, op = (a_pts, h_pts) if w == 'away' else (h_pts, a_pts)
    if typ == 'Team Total': return game_status('Team Total', 0, 0, None, ln, over, team_pts=me)
    return game_status(typ, me, op, None, ln, over)


# ---------- player stats for props (ESPN game summary box score) ----------
def prop_value(stat, box, player):
    s = norm(stat)
    k = None
    if 'rush' in s and 'rec' in s: k = ('rushing.rushingYards', 'receiving.receivingYards')
    elif 'pass' in s and 'rush' in s: k = ('passing.passingYards', 'rushing.rushingYards')
    elif 'tackle' in s: k = ('defensive.totalTackles',)
    elif 'long' in s and 'rec' in s: k = ('receiving.longReception',)
    elif 'long' in s and 'rush' in s: k = ('rushing.longRushing',)
    elif 'reception' in s and 'yard' not in s: k = ('receiving.receptions',)
    elif 'receiving yard' in s or s == 'rec yds': k = ('receiving.receivingYards',)
    elif 'rushing yard' in s or 'rush yard' in s: k = ('rushing.rushingYards',)
    elif 'rush attempt' in s or 'carries' in s: k = ('rushing.rushingAttempts',)
    elif 'passing yard' in s or 'pass yard' in s: k = ('passing.passingYards',)
    elif 'completion' in s: k = ('passing.completions/passingAttempts#0',)
    elif 'pass attempt' in s or 'passing attempt' in s: k = ('passing.completions/passingAttempts#1',)
    elif 'passing td' in s or 'pass td' in s or 'passing touchdown' in s: k = ('passing.passingTouchdowns',)
    elif 'interception' in s: k = ('passing.interceptions',)
    elif 'field goal' in s: k = ('kicking.fieldGoalsMade/fieldGoalAttempts#0',)
    if not k: return None
    nm = norm(player).split()
    if not nm: return None
    total, found = 0.0, False
    for key in k:
        cat, rest = key.split('.', 1); stat_key, idx = (rest.split('#') + [None])[:2]
        for team in box:
            for st in team.get('statistics') or []:
                if st.get('name') != cat: continue
                keys = st.get('keys') or []
                if stat_key not in keys: continue
                for a in st.get('athletes') or []:
                    an = norm((a.get('athlete') or {}).get('displayName')).split()
                    if not an or an[-1] != nm[-1] or an[0][0] != nm[0][0]: continue
                    v = (a.get('stats') or [])[keys.index(stat_key)] if keys.index(stat_key) < len(a.get('stats') or []) else ''
                    v = str(v).split('/')[int(idx)] if idx is not None else v
                    f = fnum(v)
                    if f is not None: total += f; found = True
    return total if found else None


def atd_scored(b, box, plays):
    if any(scored_by(b['player'], p.get('text', '')) and 'touchdown' in norm(((p.get('type') or {}).get('text')) or 'touchdown') for p in plays or []): return True
    return False


def main(sp, op):
    hook = 'dry' if os.environ.get('DRY_RUN') else os.environ.get('DISCORD_WEBHOOK', '').strip()
    try: state = json.load(open(sp))
    except Exception: state = {}
    if not hook:   # nothing to send to yet: keep the state as it is so nothing is skipped once the secret is added
        json.dump(state, open(op, 'w')); print('DISCORD_WEBHOOK secret is not set'); return
    state.setdefault('events', {})
    bets = load_bets()
    now = datetime.now(timezone.utc)
    days = sorted({(now.astimezone(ET) + timedelta(days=d)).strftime('%Y%m%d') for d in (-1, 0)})
    sent = 0
    for sport in ('cfb', 'nfl'):
        mine = [x for x in bets if x[0] == sport]
        if not mine: continue
        for day in days:
            try: sb = get(f"{ESPN[sport]}/scoreboard?dates={day}" + ('&groups=80&limit=400' if sport == 'cfb' else ''))
            except Exception as e: print(sport, day, 'scoreboard failed', e); continue
            for e in sb.get('events', []):
                comp = (e.get('competitions') or [{}])[0]; cs = comp.get('competitors') or []
                ca = next((c for c in cs if c.get('homeAway') == 'away'), None); ch = next((c for c in cs if c.get('homeAway') == 'home'), None)
                if not ca or not ch: continue
                eb = [b for (s_, aw, hm, b) in mine if (team_match(ca['team'], aw, sport) and team_match(ch['team'], hm, sport)) or (team_match(ca['team'], hm, sport) and team_match(ch['team'], aw, sport))]
                if not eb: continue
                st = (comp.get('status') or e.get('status') or {}).get('type', {})
                if st.get('state') == 'pre': continue
                period = int((comp.get('status') or e.get('status') or {}).get('period') or 0)
                ev = {'away': ca, 'home': ch, 'away_score': int(float(ca.get('score') or 0)), 'home_score': int(float(ch.get('score') or 0))}
                an, hn = ca['team'].get('shortDisplayName') or ca['team'].get('location'), ch['team'].get('shortDisplayName') or ch['team'].get('location')
                key = f"{sport}:{e['id']}"
                s = state['events'].setdefault(key, {'plays': None, 'final': bool(st.get('completed')) and hook != 'dry', 'h1': period > 2 and hook != 'dry', 'q1': period > 1 and hook != 'dry'})
                s.setdefault('crossed', []); s.setdefault('prop_hit', []); s.setdefault('h1', False); s.setdefault('q1', False)
                plays, box = None, []
                try:
                    summ = get(f"{ESPN[sport]}/summary?event={e['id']}")
                    plays = summ.get('scoringPlays') or []
                    box = (summ.get('boxscore') or {}).get('players') or []
                except Exception as ex: print('summary failed', e['id'], ex)
                line_of = b => fnum(b['line'])
                over_of = b => b['ou'] != 'under' and not str(b.get('side', '')).lower().startswith('under') and not b['text'].lower().startswith('under')

                # ----- scoring plays -----
                if plays is not None:
                    if s['plays'] is None: s['plays'] = max(0, len(plays) - 2) if hook == 'dry' else len(plays)   # first look: no backlog
                    for p in plays[s['plays']:]:
                        tid = str((p.get('team') or {}).get('id', ''))
                        pside = 'away' if tid and tid == str(ca['team'].get('id')) else 'home' if tid and tid == str(ch['team'].get('id')) else None
                        pp = int((p.get('period') or {}).get('number') or 0)
                        a_pts, h_pts = int(p.get('awayScore', ev['away_score'])), int(p.get('homeScore', ev['home_score']))
                        lines = []
                        for b in eb:
                            typ = b['type']
                            if typ == 'Parlay':
                                for (lt, lper, ltyp, lteam, lln) in legs_here(b, ev, sport):
                                    if not in_window(lper, pp): continue
                                    r, txt = stand(ltyp, lteam, lln, True, ev, sport, a_pts, h_pts)
                                    lines.append(f"{ICON.get(r, chr(0x2022))} {b['text']} — {lt} leg {txt}")
                            elif typ == 'Prop':
                                if is_atd(b) and scored_by(b['player'], p.get('text', '')):
                                    lines.append(f"{ICON['W']} {b['text']} — scored \U0001F389")
                                    if b['key'] not in s['prop_hit']: s['prop_hit'].append(b['key'])
                            else:
                                if not in_window(b['per'], pp): continue
                                if typ == 'Team Total' and side_of(ev, b['side'], sport) != pside: continue
                                ln, ov = line_of(b), over_of(b)
                                r, txt = stand(typ, b['side'], ln, ov, ev, sport, a_pts, h_pts)
                                lines.append(f"{ICON.get(r, chr(0x2022))} {b['text']} — {txt}")
                                if typ in ('Total', 'Team Total') and ln is not None and b['key'] not in s['crossed']:
                                    t = a_pts + h_pts if typ == 'Total' else (a_pts if side_of(ev, b['side'], sport) == 'away' else h_pts)
                                    if t > ln:
                                        s['crossed'].append(b['key'])
                                        lines.append(f"\U0001F6A8 **{b['text']} {'cashed' if ov else 'lost'}: it went over {ln:g}**")
                        if lines:
                            tm = (p.get('team') or {}).get('displayName') or ''
                            kind = (p.get('type') or {}).get('text') or 'Score'
                            clock = f"Q{pp} {(p.get('clock') or {}).get('displayValue', '')}".strip()
                            msg = f"\U0001F3C8 **{kind} {tm}** ({clock})\n**{an} {a_pts}, {hn} {h_pts}**\n_{p.get('text', '')}_\n" + '\n'.join(lines)
                            if post(hook, msg): sent += 1
                        s['plays'] += 1

                # ----- props that cleared the line (or busted an under) -----
                if sport == 'nfl' and box:
                    lines = []
                    for b in eb:
                        if b['type'] != 'Prop' or is_atd(b) or b['key'] in s['prop_hit']: continue
                        v, ln = prop_value(b['stat'], box, b['player']), line_of(b)
                        if v is None or ln is None or v <= ln: continue
                        s['prop_hit'].append(b['key'])
                        lines.append(f"{ICON['W']} {b['text']} — hit, {v:g} \U0001F3AF" if over_of(b) else f"{ICON['L']} {b['text']} — busted, {v:g}")
                    if lines and post(hook, f"\U0001F3AF **Prop update: {an} at {hn}**\n" + '\n'.join(lines)): sent += 1

                # ----- end of the first quarter / half: 1Q / 1H bets and legs -----
                ls = lambda c, n: sum(int(float(x.get('value') or 0)) for x in (c.get('linescores') or [])[:n])
                for per, done_key, n, label in (('1Q', 'q1', 1, 'END OF 1Q'), ('1H', 'h1', 2, 'HALFTIME')):
                    if s[done_key] or not (period > n or st.get('completed')): continue
                    a_p, h_p = ls(ca, n), ls(ch, n)
                    lines = []
                    for b in eb:
                        if b['type'] == 'Parlay':
                            for (lt, lper, ltyp, lteam, lln) in legs_here(b, ev, sport):
                                if lper != per: continue
                                r, _ = stand(ltyp, lteam, lln, True, ev, sport, a_p, h_p)
                                lines.append(f"{ICON.get(r, chr(0x2022))} {b['text']} — {lt} leg {'won' if r == 'W' else 'lost' if r == 'L' else 'pushed'}")
                        elif b['per'] == per:
                            r, _ = stand(b['type'], b['side'], line_of(b), over_of(b), ev, sport, a_p, h_p)
                            lines.append(f"{ICON.get(r, chr(0x2022))} {b['text']} — {'won' if r == 'W' else 'lost' if r == 'L' else 'push'}")
                    if not lines or post(hook, f"⏸️ **{label}: {an} {a_p}, {hn} {h_p}**\n" + '\n'.join(lines)):
                        s[done_key] = True; sent += 1 if lines else 0

                # ----- final -----
                if st.get('completed') and not s['final']:
                    lines = []
                    for b in eb:
                        typ = b['type']
                        if typ == 'Parlay':
                            for (lt, lper, ltyp, lteam, lln) in legs_here(b, ev, sport):
                                if lper: continue   # reported at the half / quarter
                                r, _ = stand(ltyp, lteam, lln, True, ev, sport, ev['away_score'], ev['home_score'])
                                lines.append(f"{ICON.get(r, chr(0x2022))} {b['text']} — {lt} leg {'won' if r == 'W' else 'lost' if r == 'L' else 'pushed'}")
                        elif typ == 'Prop':
                            if is_atd(b):
                                hit = b['key'] in s['prop_hit'] or atd_scored(b, box, plays)
                                lines.append(f"{ICON['W' if hit else 'L']} {b['text']} — {'won' if hit else 'lost'}")
                            else:
                                v, ln = prop_value(b['stat'], box, b['player']), line_of(b)
                                if v is None or ln is None: continue
                                r = ('W' if v > ln else 'L' if v < ln else 'P') if over_of(b) else ('W' if v < ln else 'L' if v > ln else 'P')
                                lines.append(f"{ICON[r]} {b['text']} — {'won' if r == 'W' else 'lost' if r == 'L' else 'push'} ({v:g})")
                        else:
                            if b['per']: continue   # reported at the half / quarter
                            if typ in ('Total', 'Team Total') and b['key'] in s['crossed']: continue   # already pinged when it went over
                            r, _ = stand(typ, b['side'], line_of(b), over_of(b), ev, sport, ev['away_score'], ev['home_score'])
                            if r: lines.append(f"{ICON[r]} {b['text']} — {'won' if r == 'W' else 'lost' if r == 'L' else 'push'}")
                    if not lines: s['final'] = True
                    elif post(hook, f"\U0001F3C1 **FINAL: {an} {ev['away_score']}, {hn} {ev['home_score']}**\n" + '\n'.join(lines)):
                        s['final'] = True; sent += 1
    state['updated'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    json.dump(state, open(op, 'w'), separators=(',', ':'))
    print(f'{len(bets)} open bets; {sent} alerts sent; webhook {"set" if hook else "MISSING"}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
