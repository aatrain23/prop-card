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
  for (let i = 0; i < 10 && Date.now() - t0 < 30000; i++) {
    const cs = cardsNow(); if (cs.length >= 150) break;
    const last = cs[cs.length - 1]; const lt = last && last.querySelector('time') && gameMs(last.querySelector('time').innerText.trim());
    if (lt && lt < Date.now() - 6 * 3600000) break;
    const el = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Load More Picks'); if (!el) break;
    el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect();
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
  const pulled_at = new Date().toISOString();
  const r = await fetch(URL, { method: 'POST', body: JSON.stringify({ key: KEY, action: 'sl_put', league: LEAGUE, pulled_at, picks }) });
  let j = null; try { j = await r.json(); } catch (e) {}
  return JSON.stringify({ ok: !!(j && j.ok), league: LEAGUE, found: picks.length, script: j });
})()
