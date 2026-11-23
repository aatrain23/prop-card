// Scheduled task helper: run on a SportsLine expert picks page (signed in). Loads more picks with SportsLine's own button, reads the game-line picks and their analysis,
// then posts them to Aidan's Apps Script, which stores them in his private "SportsLine picks (private)" sheet.
// The task replaces __URL__ and __KEY__ before running. Read-only on SportsLine: the only thing it presses is SportsLine's "Load More Picks" button.
(async () => {
  const URL = '__URL__', KEY = '__KEY__';
  const LEAGUE = { 'nfl': 'nfl', 'college-football': 'ncaaf', 'nba': 'nba', 'nhl': 'nhl', 'college-basketball': 'ncaab' }[location.pathname.split('/')[1]];
  if (!LEAGUE) return JSON.stringify({ ok: false, error: 'not a SportsLine league picks page: ' + location.pathname });
  if (/Log In|Sign In/.test((document.querySelector('header') || {}).innerText || '') && !document.querySelector('div.sl-epc-wrapper'))
    return JSON.stringify({ ok: false, error: 'SIGNED OUT or unreadable' });
  const MARKETS = ['Point Spread', 'Money Line', 'Over / Under'];
  const cardsNow = () => [...document.querySelectorAll('div.sl-epc-wrapper')].filter(c => (c.innerText.match(/Pick Made/g) || []).length === 1);
  const gameMs = t => { const m = /^([A-Z][a-z]{2}) (\d{1,2}) (\d{4}), (\d{1,2}):(\d{2}) ([ap]m)/i.exec(t || ''); if (!m) return null;
    return Date.UTC(+m[3], 'JanFebMarAprMayJunJulAugSepOctNovDec'.indexOf(m[1]) / 3, +m[2], (+m[4] % 12) + (/p/i.test(m[6]) ? 12 : 0) + 5, +m[5]); };
  // Load more picks (SportsLine's own "Load More Picks" button) until older games show up, at most ~150 picks or 30 seconds.
  const t0 = Date.now();
  for (let i = 0; i < 10 && Date.now() - t0 < 20000; i++) {
    const cs = cardsNow(); if (cs.length >= 150) break;
    const last = cs[cs.length - 1]; const lt = last && last.querySelector('time') && gameMs(last.querySelector('time').innerText.trim());
    if (lt && lt < Date.now() - 6 * 3600000) break;
    const el = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Load More Picks'); if (!el) break;
    el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); if (!r.width) break;
    const o = { bubbles: true, cancelable: true, view: window, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, button: 0 };
    ['pointerover', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(t => el.dispatchEvent(t.startsWith('pointer') ? new PointerEvent(t, { ...o, pointerId: 1, pointerType: 'mouse', isPrimary: true }) : new MouseEvent(t, o)));
    const before = cs.length; for (let w = 0; w < 10 && cardsNow().length === before; w++) await new Promise(res => setTimeout(res, 400));
    if (cardsNow().length === before) break;
  }
  const cards = cardsNow();
  const seen = new Set(), picks = [];
  for (const c of cards) {
    const L = [...c.querySelectorAll('*')].filter(e => !e.children.length && e.innerText && e.innerText.trim()).map(e => ({ t: e.tagName, s: e.innerText.trim() }));
    const s = L.map(x => x.s), u = s.indexOf('Unit'); if (u < 4) continue;
    const market = s[u - 2]; if (!MARKETS.includes(market)) continue;
    const times = L.filter(x => x.t === 'TIME').map(x => x.s);
    const gm = gameMs(times[0]); if (gm && gm < Date.now() - 6 * 3600000) continue;   // game already over
    const p = { game_time: times[0] || '', away_nick: s[u - 4], home_nick: s[u - 3].replace(/^@\s*/, ''), market, pick: s[u - 1], units: s[u + 1],
      expert: s[u + 2], nickname: s[u + 3] && s[u + 3] !== 'Profile →' ? s[u + 3] : '', record: s.find(x => /in Last \d+/.test(x)) || '',
      analysis: [...c.querySelectorAll('p')].map(x => x.innerText.trim()).filter(Boolean).join('\n\n'), made: times[1] || '',
      book: (s.find(x => /^on\s/.test(x)) || '').replace(/^on\s+/, '') };
    const k = [p.game_time, p.away_nick, p.home_nick, p.market, p.pick, p.expert].join('|');
    if (seen.has(k)) continue; seen.add(k); picks.push(p);
  }
  // Expert profiles: every expert's pending picks for this league. The league page only shows ~15 featured picks, and team totals
  // ("Total Home Points" / "Total Away Points") only appear on profiles. Same-origin reads of pages the signed-in user can see.
  let profiles = 0, fromProfiles = 0;
  try {
    const seg = location.pathname.split('/')[1];
    const rsc = html => { const o = []; const re = /self\.__next_f\.push\((\[[\s\S]*?\])\)<\/script>/g; let m; while ((m = re.exec(html))) { try { const a = JSON.parse(m[1]); if (typeof a[1] === 'string') o.push(a[1]); } catch (e) {} } return o.join(''); };
    const objAt = (x, i) => { let d = 0, q = false, e = false; for (let k = i; k < x.length; k++) { const ch = x[k]; if (q) { if (e) e = false; else if (ch === '\\') e = true; else if (ch === '"') q = false; continue; } if (ch === '"') q = true; else if (ch === '{') d++; else if (ch === '}') { d--; if (!d) return x.slice(i, k + 1); } } return null; };
    const picksIn = html => { const x = rsc(html), o = []; let i = 0; while ((i = x.indexOf('{"cursor":', i)) >= 0) { const ob = objAt(x, i); i++; if (!ob) continue; try { const n = JSON.parse(ob).node; if (n && n.__typename === 'SportsLineExpertPick') o.push(n); } catch (e) {} } return o; };
    const et = iso => { const d = new Date(iso); const f = o => d.toLocaleString('en-US', { timeZone: 'America/New_York', ...o });
      return `${f({ month: 'short' })} ${f({ day: 'numeric' })} ${f({ year: 'numeric' })}, ${f({ hour: 'numeric', minute: '2-digit' }).toLowerCase()} ET`; };
    const dir = await (await fetch('/experts/')).text();
    const ids = [...new Set([...dir.matchAll(/\/experts\/(\d+)\/([a-z0-9-]+)\//g)].map(m => m[1] + '/' + m[2]))];
    const MK = { 'Point Spread': 1, 'Money Line': 1, 'Over / Under': 1, 'Total Home Points': 'Team Total', 'Total Away Points': 'Team Total' };
    await Promise.all(ids.map(async id => {
      let list = []; try { list = picksIn(await (await fetch(`/experts/${id}/?league=${seg}`)).text()); profiles++; } catch (e) { return; }
      for (const n of list) {
        const sel = n.selection || {}, g = n.context || {}, mk = MK[sel.marketDisplayName];
        if (!mk || sel.resultStatus !== 'PENDING' || !g.homeTeam || !g.gameScheduledTime) continue;
        if (new Date(g.gameScheduledTime).getTime() < Date.now()) continue;           // started: locked anyway
        const market = mk === 1 ? sel.marketDisplayName : mk;
        const pick = String(sel.label || '').replace(/\s+Total Pts(?=\s+[+-]\d{3,}$)/, '');
        const ex = n.expert || {}, expert = [ex.firstName, ex.lastName].filter(Boolean).join(' ');
        const p = { game_time: et(g.gameScheduledTime), away_nick: g.awayTeam.nickname, home_nick: g.homeTeam.nickname, market, pick, units: String(sel.unit ?? n.unit ?? ''),
          expert, nickname: ex.nickName || '', record: ((n.expertStreaks || [])[0] || {}).label || '', analysis: n.analysis || '', made: n.createdAt ? et(n.createdAt) : '',
          book: sel.sportsbookDisplayName || '' };
        const k = [p.game_time, p.away_nick, p.home_nick, p.market, p.pick, p.expert].join('|');
        const k2 = [p.away_nick, p.home_nick, p.market, p.pick, p.expert].join('|');
        if (seen.has(k) || picks.some(q => [q.away_nick, q.home_nick, q.market, q.pick, q.expert].join('|') === k2)) continue;
        seen.add(k); picks.push(p); fromProfiles++;
      }
    }));
  } catch (e) {}
  let props = 0;
  if (LEAGUE === 'nfl') try {   // NFL player-prop picks (Aidan, Nov 23 2026), from SportsLine's own picks API
    const etp = iso => { const d = new Date(iso); const f = o => d.toLocaleString('en-US', { timeZone: 'America/New_York', ...o });
      return `${f({ month: 'short' })} ${f({ day: 'numeric' })} ${f({ year: 'numeric' })}, ${f({ hour: 'numeric', minute: '2-digit' }).toLowerCase()} ET`; };
    const Q = 'query($f:ExpertPicksInputFilter,$a:Int){expertPicksV2(input:{league:["NFL"]},filter:$f,first:200,after:$a){edges{node{created scheduledDateTime selectionLabel sportsbookName unit writeup awayTeam{abbr} homeTeam{abbr} authorInfo{firstName lastName} selection{... on ExpertPickPlayersPropsSelection{marketName}}}} pageInfo{hasNextPage endCursor}}}';
    let after = 0;
    for (let i = 0; i < 10; i++) {
      const j = await (await fetch('/ui-gateway/v1/graphql', { method: 'POST', headers: { 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify({ query: Q, variables: { f: { marketType: ['PROP'], status: ['PENDING'] }, a: after } }) })).json();
      if (!j.data) break; const c = j.data.expertPicksV2;
      for (const e of c.edges) { const n = e.node;
        if (!n.selection || !n.selection.marketName || !n.selectionLabel || !n.awayTeam || !n.homeTeam) continue;
        if (new Date(n.scheduledDateTime).getTime() < Date.now()) continue;
        const tmp = document.createElement('div'); tmp.innerHTML = n.writeup || '';
        const p = { game_time: etp(n.scheduledDateTime), away_nick: n.awayTeam.abbr, home_nick: n.homeTeam.abbr, market: 'Player Prop', pick: n.selectionLabel,
          units: String(n.unit ?? ''), expert: [n.authorInfo?.firstName, n.authorInfo?.lastName].filter(Boolean).join(' '), nickname: '', record: '',
          analysis: (tmp.innerText || '').trim(), made: n.created ? etp(n.created) : '', book: n.sportsbookName || '' };
        const k = [p.game_time, p.away_nick, p.home_nick, p.market, p.pick, p.expert].join('|');
        if (seen.has(k)) continue; seen.add(k); picks.push(p); props++; }
      if (!c.pageInfo.hasNextPage) break; after = +c.pageInfo.endCursor;
    }
  } catch (e) {}
  const pulled_at = new Date().toISOString();
  const r = await fetch(URL, { method: 'POST', body: JSON.stringify({ key: KEY, action: 'sl_put', league: LEAGUE, pulled_at, picks }) });
  let j = null; try { j = await r.json(); } catch (e) {}
  return JSON.stringify({ ok: !!(j && j.ok), league: LEAGUE, found: picks.length, profiles, fromProfiles, teamTotals: picks.filter(p => p.market === 'Team Total').length, props, script: j });
})()
