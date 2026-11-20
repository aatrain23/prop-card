// Run on a SportsLine expert picks page (e.g. https://www.sportsline.com/college-football/picks/experts/) while signed in.
// Returns JSON: {league, n, picks:[{game_time, away_nick, home_nick, market, pick, units, expert, nickname, record, analysis, made, book}]}
// Read-only: reads the page text; clicks nothing.
(() => {
  const LEAGUE = location.pathname.split('/')[1];
  const cards = [...document.querySelectorAll('div.sl-epc-wrapper')].filter(c => (c.innerText.match(/Pick Made/g) || []).length === 1);
  const out = [];
  for (const c of cards) {
    const L = [...c.querySelectorAll('*')].filter(e => !e.children.length && e.innerText && e.innerText.trim()).map(e => ({ t: e.tagName, s: e.innerText.trim() }));
    const s = L.map(x => x.s);
    const u = s.indexOf('Unit'); if (u < 4) continue;
    const times = L.filter(x => x.t === 'TIME').map(x => x.s);
    const away = s[u - 4], home = s[u - 3].replace(/^@\s*/, ''), market = s[u - 2], pick = s[u - 1];
    const expert = s[u + 2], nick = s[u + 3] && s[u + 3] !== 'Profile →' ? s[u + 3] : '';
    const record = s.find(x => /in Last \d+/.test(x)) || '';
    const analysis = [...c.querySelectorAll('p')].map(p => p.innerText.trim()).filter(Boolean).join('\n\n');
    const book = (s.find(x => /^on\s/.test(x)) || '').replace(/^on\s+/, '');
    out.push({ game_time: times[0] || '', away_nick: away, home_nick: home, market, pick, units: s[u + 1], expert, nickname: nick, record, analysis, made: times[1] || '', book });
  }
  const seen = new Set();
  const picks = out.filter(p => { const k = [p.game_time, p.away_nick, p.home_nick, p.market, p.pick, p.expert].join('|'); if (seen.has(k)) return false; seen.add(k); return true; });
  return JSON.stringify({ league: LEAGUE, url: location.href, n: picks.length, picks });
})()
