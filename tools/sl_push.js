// Scheduled task helper: run on a SportsLine expert picks page (signed in). Reads the game-line picks and their analysis,
// then posts them to Aidan's Apps Script, which stores them in his private "SportsLine picks (private)" sheet.
// The task replaces __URL__ and __KEY__ before running. Read-only on SportsLine: clicks nothing.
(async () => {
  const URL = '__URL__', KEY = '__KEY__';
  const LEAGUE = { 'nfl': 'nfl', 'college-football': 'ncaaf', 'nba': 'nba', 'nhl': 'nhl', 'college-basketball': 'ncaab' }[location.pathname.split('/')[1]];
  if (!LEAGUE) return JSON.stringify({ ok: false, error: 'not a SportsLine league picks page: ' + location.pathname });
  if (/Log In|Sign In/.test((document.querySelector('header') || {}).innerText || '') && !document.querySelector('div.sl-epc-wrapper'))
    return JSON.stringify({ ok: false, error: 'SIGNED OUT or unreadable' });
  const MARKETS = ['Point Spread', 'Money Line', 'Over / Under'];
  const cards = [...document.querySelectorAll('div.sl-epc-wrapper')].filter(c => (c.innerText.match(/Pick Made/g) || []).length === 1);
  const seen = new Set(), picks = [];
  for (const c of cards) {
    const L = [...c.querySelectorAll('*')].filter(e => !e.children.length && e.innerText && e.innerText.trim()).map(e => ({ t: e.tagName, s: e.innerText.trim() }));
    const s = L.map(x => x.s), u = s.indexOf('Unit'); if (u < 4) continue;
    const market = s[u - 2]; if (!MARKETS.includes(market)) continue;
    const times = L.filter(x => x.t === 'TIME').map(x => x.s);
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
