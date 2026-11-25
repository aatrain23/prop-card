// Apps Script for the "CFB Bet Card feed" Google Sheet: lets the Line Shop add a bet row (college football here, UFC to the "UFC Bet Card feed" sheet), the College football page remove one before kickoff,
// and stores / serves SportsLine expert picks in Aidan's private "SportsLine picks (private)" sheet (key required for both).
// Nov 23 2026: also adds / removes NFL player props on the "Props" tab of the "NFL Card feed (props + StackLine)" sheet (sport 'nfl'),
// from the NFL props page's pre-game board, with a "Why this bet" row on "Props Why".
// Nov 24 2026: CFB and UFC bets added from the Line Shop also carry your own "Why this bet" reason into the card's why column (added if the sheet lacks one). Updating: paste this file over the old one
// but KEEP YOUR OWN KEY line, save, then Deploy > Manage deployments > (pencil) > Version: New version > Deploy (the URL stays the same).
// Setup (once): in the sheet, Extensions > Apps Script, paste this whole file, save, then
// Deploy > New deployment > type "Web app", Execute as "Me", Who has access "Anyone", Deploy, authorize,
// and copy the Web app URL into the Line Shop's "College football card" settings with the key below.
const KEY = 'PASTE-YOUR-KEY-HERE';
const SL_SHEET_ID = '1syDw8VXPgV_8cOwd5Jsw00vmj_6QxioIvj97S3jr3GA';   // SportsLine picks (private)
const UFC_SHEET_ID = '1yQBNGmSFXWw9lrWt7PYaM6FY324DPrpB5P_Njka-hCQ';  // UFC Bet Card feed (row 1 headers, row 2 event/date/updated/unit, bets from row 3)
const NFL_SHEET_ID = '1NFglRlEFzv1eccTJ8Cl2rAZcbEseBTacd2MZqI4p41M'; // NFL Card feed (Props: row 1 headers, row 2 week/updated/record + first bet, more bets below)
const SL_COLS = ['league','game_time','away_nick','home_nick','market','pick','units','expert','nickname','record','analysis','made','book','pulled_at'];   // the same key goes into the Line Shop settings; change both if you ever want a new one

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.key !== KEY) return out({ ok: false, error: 'wrong key' });
    const sh = SpreadsheetApp.getActive().getSheets()[0];
    const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
    if (d.action === 'sl_put') return slPut(d);
    if (d.action === 'alert_add') return alertAdd(d);
    if (d.action === 'alert_remove') return alertRemove(d);
    if (d.sport === 'nfl') return d.action === 'remove' ? removeNfl(d) : addNfl(d);
    if (d.sport === 'ufc') return d.action === 'remove' ? removeUfc(d) : addUfc(d);
    if (d.action === 'remove') return removeBet(sh, head, d);
    const week = sh.getRange('A2').getValue();
    // don't add the same bet twice (same matchup, bet, book and odds)
    const last = sh.getLastRow();
    if (last >= 3) {
      const rows = sh.getRange(3, 1, last - 2, head.length).getDisplayValues();
      const ix = n => head.indexOf(n);
      if (rows.some(r => r[ix('matchup')] === d.matchup && r[ix('bet')] === d.bet && r[ix('book')] === d.book && r[ix('odds')] === String(d.odds)))
        return out({ ok: true, duplicate: true });
    }
    const v = { week: week, date: d.date, kickoff: d.kickoff, matchup: d.matchup, away: d.away, home: d.home, bet: d.bet,
                type: d.type, side: d.side, line: d.line === '' ? '' : "'" + d.line, odds: "'" + d.odds, book: d.book, result: '', note: d.note, why: safeTxt(d.why) };
    const hw = withWhy(sh, head, d.why);
    sh.appendRow(hw.map(h => (h in v ? v[h] : '')));
    const iu = head.indexOf('updated');
    if (iu >= 0) sh.getRange(2, iu + 1).setValue(Utilities.formatDate(new Date(), 'America/New_York', "MMM d, h:mm a 'ET'"));
    return out({ ok: true, row: sh.getLastRow() });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  }
}
// Remove one bet row, only while its game hasn't started and it has no result. Bets lock at kickoff.
function removeBet(sh, head, d) {
  const last = sh.getLastRow();
  if (last < 3) return out({ ok: false, error: 'bet not found' });
  const rows = sh.getRange(3, 1, last - 2, head.length).getDisplayValues();
  const ix = n => head.indexOf(n);
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    if (r[ix('matchup')] !== d.matchup || r[ix('bet')] !== d.bet || r[ix('book')] !== (d.book || '') || r[ix('odds')] !== String(d.odds || '')) continue;
    if (r[ix('result')]) return out({ ok: false, error: 'this bet is already graded' });
    let kick = null;
    try { kick = Utilities.parseDate(r[ix('date')] + ' ' + r[ix('kickoff')], 'America/New_York', 'yyyyMMdd h:mm a'); } catch (err) {}
    if (!kick) return out({ ok: false, error: 'no kickoff time on this bet, so it can\'t be checked; remove it in the sheet' });
    if (new Date() >= kick) return out({ ok: false, error: 'the game has started, so this bet is locked in' });
    sh.deleteRow(i + 3);
    const iu = ix('updated');
    if (iu >= 0) sh.getRange(2, iu + 1).setValue(Utilities.formatDate(new Date(), 'America/New_York', "MMM d, h:mm a 'ET'"));
    return out({ ok: true, removed: true });
  }
  return out({ ok: false, error: 'bet not found on the card' });
}
// UFC: add one bet to the UFC Bet Card feed (its first tab). Sets the card's event and date on row 2 if they're empty or from an older card.
function addUfc(d) {
  const sh = SpreadsheetApp.openById(UFC_SHEET_ID).getSheets()[0];
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    const ix = n => head.indexOf(n);
    const last = sh.getLastRow();
    if (last >= 3) {
      const rows = sh.getRange(3, 1, last - 2, head.length).getDisplayValues();
      if (rows.some(r => r[ix('fight')] === d.fight && r[ix('bet')] === d.bet && r[ix('book')] === d.book && r[ix('odds')] === String(d.odds)))
        return out({ ok: true, duplicate: true });
    }
    const curDate = String(sh.getRange(2, ix('date') + 1).getDisplayValue() || '');
    if (d.date && (!curDate || curDate < d.date)) {
      if (ix('date') >= 0) sh.getRange(2, ix('date') + 1).setValue("'" + d.date);
      if (ix('event') >= 0 && d.event) sh.getRange(2, ix('event') + 1).setValue(d.event);
    }
    const v = { fight: d.fight, card: d.card || '', time: d.time, bet: d.bet, type: d.type, pick: d.pick, odds: "'" + d.odds, book: d.book,
                units: d.units, result: '', note: d.note, why: safeTxt(d.why) };
    const hw = withWhy(sh, head, d.why);
    sh.appendRow(hw.map(h => (h in v ? v[h] : '')));
    if (ix('updated') >= 0) sh.getRange(2, ix('updated') + 1).setValue(Utilities.formatDate(new Date(), 'America/New_York', "MMM d, h:mm a 'ET'"));
    return out({ ok: true, row: sh.getLastRow() });
  } finally { lock.releaseLock(); }
}
// UFC: remove one bet, only before its fight starts (card date on row 2 + the bet's time) and while it has no result. Bets lock at fight time.
function removeUfc(d) {
  const sh = SpreadsheetApp.openById(UFC_SHEET_ID).getSheets()[0];
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    const ix = n => head.indexOf(n);
    const last = sh.getLastRow();
    if (last < 3) return out({ ok: false, error: 'bet not found' });
    const date = String(sh.getRange(2, ix('date') + 1).getDisplayValue() || '').replace(/^'/, '');
    const rows = sh.getRange(3, 1, last - 2, head.length).getDisplayValues();
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i];
      if (r[ix('fight')] !== d.fight || r[ix('bet')] !== d.bet || r[ix('book')] !== (d.book || '') || r[ix('odds')] !== String(d.odds || '')) continue;
      if (r[ix('result')]) return out({ ok: false, error: 'this bet is already graded' });
      let start = null;
      try { start = Utilities.parseDate(date + ' ' + r[ix('time')], 'America/New_York', 'yyyyMMdd h:mm a'); } catch (err) {}
      if (!start) return out({ ok: false, error: 'no fight time on this bet, so it can\'t be checked; remove it in the sheet' });
      if (new Date() >= start) return out({ ok: false, error: 'the fight has started, so this bet is locked in' });
      sh.deleteRow(i + 3);
      if (ix('updated') >= 0) sh.getRange(2, ix('updated') + 1).setValue(Utilities.formatDate(new Date(), 'America/New_York', "MMM d, h:mm a 'ET'"));
      return out({ ok: true, removed: true });
    }
    return out({ ok: false, error: 'bet not found on the card' });
  } finally { lock.releaseLock(); }
}
// SportsLine picks: replace one league's rows with a fresh pull (posted by the scheduled task from the SportsLine page).
function slPut(d) {
  const sh = SpreadsheetApp.openById(SL_SHEET_ID).getSheets()[0];
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const last = sh.getLastRow();
    const keep = last >= 2 ? sh.getRange(2, 1, last - 1, SL_COLS.length).getValues().filter(r => r[0] !== d.league) : [];
    const safe = v => { v = v == null ? '' : String(v); return /^[=+\-@]/.test(v) ? "'" + v : v; };
    const fresh = (d.picks || []).map(p => SL_COLS.map(c => c === 'league' ? d.league : c === 'pulled_at' ? d.pulled_at : safe(p[c])));
    const rows = keep.concat(fresh);
    if (last >= 2) sh.getRange(2, 1, last - 1, SL_COLS.length).clearContent();
    if (rows.length) sh.getRange(2, 1, rows.length, SL_COLS.length).setValues(rows);
    return out({ ok: true, league: d.league, stored: fresh.length, total: rows.length });
  } finally { lock.releaseLock(); }
}
// NFL: add one player prop to the Props tab. Columns A-F of row 2 hold the week header; the first bet shares row 2.
const NFL_BET_COLS = ['date','game','kick','player','team','side','line','stat','odds','book','expert','model','worst','stake','result','proj'];
const nflNorm = s => String(s || '').toLowerCase().replace(/[^a-z]/g, '');
function nflRows(sh) {
  const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
  const last = sh.getLastRow();
  const rows = last >= 2 ? sh.getRange(2, 1, last - 1, head.length).getDisplayValues() : [];
  return { head, ix: n => head.indexOf(n), rows };
}
function nflSame(r, ix, d) {
  return r[ix('date')].replace(/^'/, '') === d.date && nflNorm(r[ix('player')]) === nflNorm(d.player) && r[ix('side')] === d.side && nflNorm(r[ix('stat')]) === nflNorm(d.stat);
}
function nflStamp(sh) { sh.getRange('B2').setValue(Utilities.formatDate(new Date(), 'America/New_York', 'MMM d h:mm a')); }
function addNfl(d) {
  const ss = SpreadsheetApp.openById(NFL_SHEET_ID), sh = ss.getSheetByName('Props');
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    if (!d.player || !d.date || !d.side || !d.stat) return out({ ok: false, error: 'missing bet details' });
    const T = nflRows(sh), ix = T.ix;
    if (T.rows.some(r => nflSame(r, ix, d))) return out({ ok: true, duplicate: true });
    const safe = v => { v = v == null ? '' : String(v); return /^[=+@]/.test(v) ? "'" + v : v; };
    const v = { date: "'" + d.date, game: safe(d.game), kick: safe(d.kick), player: safe(d.player), team: safe(d.team), side: d.side, line: +d.line, stat: safe(d.stat),
                odds: +d.odds, book: safe(d.book), expert: safe(d.expert), model: d.model ? "'" + d.model : '', worst: -150, stake: +d.stake, result: '', proj: d.proj === '' || d.proj == null ? '' : +d.proj };
    const row2Free = T.rows.length && !T.rows[0][ix('player')];
    const r = row2Free ? 2 : sh.getLastRow() + 1;
    NFL_BET_COLS.forEach(c => { const i = ix(c); if (i >= 0) sh.getRange(r, i + 1).setValue(v[c]); });
    nflStamp(sh);
    if (d.why) {
      const w = ss.getSheetByName('Props Why');
      if (w) {
        const lw = w.getLastRow(), have = lw >= 2 ? w.getRange(2, 1, lw - 1, 4).getDisplayValues() : [];
        if (!have.some(x => x[0] === d.date && nflNorm(x[1]) === nflNorm(d.player) && x[2] === d.side && String(+x[3]) === String(+d.line)))
          w.appendRow(["'" + d.date, d.player, d.side, +d.line, d.stat, safe(d.why)]);
      }
    }
    return out({ ok: true, row: r });
  } finally { lock.releaseLock(); }
}
// NFL: remove one bet, only before kickoff and while it has no result.
function removeNfl(d) {
  const ss = SpreadsheetApp.openById(NFL_SHEET_ID), sh = ss.getSheetByName('Props');
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const T = nflRows(sh), ix = T.ix;
    for (let i = T.rows.length - 1; i >= 0; i--) {
      const r = T.rows[i]; if (!nflSame(r, ix, d)) continue;
      if (r[ix('result')]) return out({ ok: false, error: 'this bet is already graded' });
      let kick = null; try { kick = Utilities.parseDate(r[ix('date')].replace(/^'/, '') + ' ' + r[ix('kick')], 'America/New_York', 'yyyy-MM-dd h:mm a'); } catch (err) {}
      if (!kick) return out({ ok: false, error: 'no kickoff time on this bet; remove it in the sheet' });
      if (new Date() >= kick) return out({ ok: false, error: 'the game has started, so this bet is locked in' });
      const row = i + 2;
      if (row === 2) NFL_BET_COLS.forEach(c => { const k = ix(c); if (k >= 0) sh.getRange(2, k + 1).clearContent(); });   // keep the week header in A-F
      else sh.deleteRow(row);
      const w = ss.getSheetByName('Props Why');
      if (w && w.getLastRow() >= 2) {
        const have = w.getRange(2, 1, w.getLastRow() - 1, 4).getDisplayValues();
        for (let j = have.length - 1; j >= 0; j--) if (have[j][0] === d.date && nflNorm(have[j][1]) === nflNorm(d.player) && have[j][2] === d.side) { w.deleteRow(j + 2); break; }
      }
      nflStamp(sh);
      return out({ ok: true, removed: true });
    }
    return out({ ok: false, error: 'bet not found on the card' });
  } finally { lock.releaseLock(); }
}
function doGet(e) {
  const q = (e && e.parameter) || {};
  if (q.action === 'alerts') { if (q.key !== KEY) return out({ ok: false, error: 'wrong key' }); return alertList(); }
  if (q.action === 'sl') {
    if (q.key !== KEY) return out({ ok: false, error: 'wrong key' });
    const sh = SpreadsheetApp.openById(SL_SHEET_ID).getSheets()[0];
    const last = sh.getLastRow();
    const vals = last >= 2 ? sh.getRange(2, 1, last - 1, SL_COLS.length).getDisplayValues() : [];
    return out({ ok: true, picks: vals.map(r => Object.fromEntries(SL_COLS.map((c, i) => [c, r[i]]))) });
  }
  return out({ ok: true, sheet: SpreadsheetApp.getActive().getName(), ufc: true, alerts: true });
}
// Your own "Why this bet" text: kept as plain text, and a why column is added to the card's header row if there isn't one yet.
function safeTxt(v) { v = v == null ? '' : String(v); return /^[=+\-@]/.test(v) ? "'" + v : v; }
function withWhy(sh, head, why) {
  head = head.map(String);
  if (!why || head.indexOf('why') >= 0) return head;
  sh.getRange(1, head.length + 1).setValue('why');
  return head.concat(['why']);
}
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

// ---------- Line alerts (Nov 24 2026) ----------
// The Line Shop's "Alert me" box saves a target here (tab "Line Alerts" of this sheet). checkAlerts runs every 5 minutes, reads the main lines
// at FanDuel, BetMGM, Caesars and Fanatics from Action Network plus Novig and Kalshi (Nov 24 2026), and pushes to Aidan's phone through the free ntfy app when any book reaches
// the target number (spread / total) and the target price, if one was set (moneyline alerts are price only). Each alert fires once; it expires at game start.
// Setup (once): after pasting and deploying this file, choose setupAlerts in the function menu at the top and click Run (allow the new permissions).
// The Execution log then shows your ntfy topic: install ntfy on your phone, tap +, and subscribe to that topic. A test alert is sent right away.
const ALERT_COLS = ['id','created','league','game_id','game','start','market','side','label','target','odds','status','hit_at','hit'];
const AN_BOOKS_GS = { 69: 'FanDuel', 75: 'BetMGM', 49: 'Caesars', 2988: 'Fanatics' };
const LINE_SHOP_URL = 'https://aatrain23.github.io/prop-card/lines.html';
function alertSheet() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName('Line Alerts');
  if (!sh) { sh = ss.insertSheet('Line Alerts'); sh.getRange(1, 1, 1, ALERT_COLS.length).setValues([ALERT_COLS]); sh.setFrozenRows(1); }
  return sh;
}
function alertRows(sh) {
  const last = sh.getLastRow();
  return last >= 2 ? sh.getRange(2, 1, last - 1, ALERT_COLS.length).getValues().map(r => Object.fromEntries(ALERT_COLS.map((c, i) => [c, r[i]]))) : [];
}
const amer = o => (o > 0 ? '+' : '') + Math.round(o);
const alertDec = a => a > 0 ? 1 + a / 100 : 1 + 100 / Math.abs(a);
function alertText(a) {
  const t = a.target === '' || a.target == null ? '' : (a.market === 'spread' && +a.target > 0 ? '+' : '') + a.target;
  const o = a.odds === '' || a.odds == null ? '' : amer(+a.odds) + ' or better';
  if (a.market === 'moneyline') return a.label + ' ML at ' + o;
  return a.label + ' ' + t + (a.market === 'spread' ? ' or better' : a.side === 'over' ? ' or lower' : ' or higher') + (o ? ', at ' + o : '');
}
function alertAdd(d) {
  const sh = alertSheet();
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    if (!d.game_id || !d.market || !d.side) return out({ ok: false, error: 'missing alert details' });
    const target = d.target === '' || d.target == null ? '' : +d.target, odds = d.odds === '' || d.odds == null ? '' : +d.odds;
    if (d.market === 'moneyline' ? odds === '' : target === '') return out({ ok: false, error: d.market === 'moneyline' ? 'a moneyline alert needs a price' : 'set the number you want' });
    if ((target !== '' && isNaN(target)) || (odds !== '' && (isNaN(odds) || Math.abs(odds) < 100))) return out({ ok: false, error: 'the number or price is not valid' });
    const id = Utilities.getUuid().slice(0, 8);
    const a = { id, created: new Date(), league: d.league, game_id: String(d.game_id), game: d.game, start: d.start, market: d.market, side: String(d.side), label: d.label,
                target, odds, status: 'active', hit_at: '', hit: '' };
    sh.appendRow(ALERT_COLS.map(c => c === 'game' || c === 'label' ? safeTxt(a[c]) : a[c]));
    return out({ ok: true, id, text: alertText(a) });
  } finally { lock.releaseLock(); }
}
function alertRemove(d) {
  const sh = alertSheet();
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const rows = alertRows(sh);
    for (let i = rows.length - 1; i >= 0; i--) if (rows[i].id === d.id) { sh.deleteRow(i + 2); return out({ ok: true, removed: true }); }
    return out({ ok: false, error: 'alert not found' });
  } finally { lock.releaseLock(); }
}
function alertList() {
  const rows = alertRows(alertSheet()).filter(a => a.status === 'active' || (a.hit_at && Date.now() - new Date(a.hit_at).getTime() < 3 * 86400000));
  return out({ ok: true, alerts: rows.map(a => ({ id: a.id, league: a.league, game_id: a.game_id, game: a.game, start: a.start, status: a.status, text: alertText(a), hit: a.hit, hit_at: a.hit_at ? new Date(a.hit_at).toISOString() : '' })) });
}
// Every price for this alert's side: the four books' main lines from Action Network, plus Novig's and Kalshi's lines (each marked main or alt).
const NV_LEAGUE = { ncaaf: 'NCAAF', nfl: 'NFL', ncaab: 'NCAAB', nba: 'NBA', nhl: 'NHL' };
const KALSHI_JSON = 'https://raw.githubusercontent.com/aatrain23/prop-card/kalshi-data/kalshi.json';
const aNorm = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/&/g, ' and ').replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
function aSame(t, name, symbol) {
  const n = aNorm(name), sy = aNorm(symbol), names = [t.display_name, t.full_name, t.location, t.short_name, t.nickname].filter(Boolean).map(aNorm);
  if (sy && aNorm(t.abbr) === sy) return true;
  return names.some(x => x && (x === n || (n.length > 3 && (x.startsWith(n + ' ') || n.startsWith(x + ' ')))));
}
const kName = n => String(n || '').replace(/\bSt\.?$/, 'State').replace(/\bSt\.\s/, 'State ');
const kSameA = (t, n, c) => aSame(t, n, c) || aSame(t, kName(n), c);
const c2a = p => p >= 0.5 ? -100 * p / (1 - p) : 100 * (1 - p) / p;
const kOK = p => p != null && p > 0.02 && p < 0.98;
const kAm = p => c2a(Math.min(0.99, p + 0.07 * p * (1 - p)));   // Kalshi ask plus its taker fee, as the Line Shop shows it
function getJ(url, ctx) {
  if (url in ctx.http) return ctx.http[url];
  let j = null;
  try { const r = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } }); if (r.getResponseCode() < 300) j = JSON.parse(r.getContentText()); } catch (e) {}
  return (ctx.http[url] = j);
}
function novigOutcomes(a, g, ctx) {
  const lg = NV_LEAGUE[a.league]; if (!lg) return null;
  const list = getJ('https://api.novig.us/nbx/v1/events/league-list?league=' + lg, ctx); if (!list) return null;
  const evs = Array.isArray(list) ? list : (list.events || []), t0 = new Date(g.start_time).getTime();
  const away = g.teams.find(t => t.id === g.away_team_id), home = g.teams.find(t => t.id === g.home_team_id);
  let best = null, bs = 0;
  for (const e of evs) {
    if (Math.abs(new Date(e.scheduledStart).getTime() - t0) > 3 * 3600000) continue;
    const sc = (e.awayTeam && aSame(away, e.awayTeam.displayName, e.awayTeam.symbol) ? 1 : 0) + (e.homeTeam && aSame(home, e.homeTeam.displayName, e.homeTeam.symbol) ? 1 : 0);
    if (sc > bs) { best = e; bs = sc; }
  }
  if (!best) return null;
  const m = getJ('https://api.novig.us/nbx/v1/event-details/' + best.eventId + '/markets', ctx), st = getJ('https://api.novig.us/nbx/v1/event-details/' + best.eventId + '/markets/state', ctx);
  if (!m || !st) return null;
  const flat = []; for (const mk of m.markets) for (const o of mk.outcomes) flat.push({ type: mk.type, desc: o.description, comp: o.competitorId });
  const avail = (st.outcomes && st.outcomes.available) || []; if (avail.length !== flat.length) return null;
  flat.forEach((f, i) => { f.ask = avail[i] == null ? null : parseFloat(avail[i]); });
  return { outcomes: flat, competitors: m.competitors || {} };
}
function kalshiGame(a, g, ctx) {
  const k = getJ(KALSHI_JSON + '?t=' + Math.floor(Date.now() / 60000), ctx); if (!k || !k.games) return null;
  const away = g.teams.find(t => t.id === g.away_team_id), home = g.teams.find(t => t.id === g.home_team_id), t0 = new Date(g.start_time).getTime();
  let best = null, bd = Infinity;
  for (const x of k.games) {
    if (x.league !== a.league) continue;
    const dt = Math.abs(new Date(x.exp).getTime() - t0); if (dt > 30 * 3600000) continue;
    const ents = Object.entries(x.teams || {});
    if (ents.length < 2) [...new Set((x.spread || []).map(r => r.code + '|' + r.team))].forEach(s => ents.push(s.split('|')));
    const has = t => ents.some(([c, n]) => kSameA(t, n, c));
    if (has(away) && has(home) && dt < bd) { best = x; bd = dt; }
  }
  return best;
}
function alertOffers(a, g, ctx) {
  const out = [], team = a.market === 'total' ? null : g.teams.find(t => String(t.id) === a.side);
  for (const bid in AN_BOOKS_GS) {
    const ev = g.markets && g.markets[bid] && g.markets[bid].event; if (!ev) continue;
    const arr = (ev[a.market] || []).filter(x => !x.is_live && x.odds != null);
    const x = a.market === 'total' ? arr.find(y => y.side === a.side) : arr.find(y => String(y.team_id) === a.side);
    if (x) out.push({ book: AN_BOOKS_GS[bid], value: x.value, odds: x.odds, main: true });
  }
  const nv = novigOutcomes(a, g, ctx);
  if (nv) {
    const rows = [];
    for (const o of nv.outcomes) {
      if (o.ask == null || !(o.ask > 0 && o.ask < 1)) continue;
      if (a.market === 'total' && o.type === 'TOTAL') { const m = /^(over|under)\s+(\d+(?:\.\d+)?)/i.exec(o.desc || ''); if (m && m[1].toLowerCase() === a.side) rows.push({ value: parseFloat(m[2]), ask: o.ask }); continue; }
      if (a.market === 'total') continue;
      const c = nv.competitors[o.comp]; if (!c || !aSame(team, c.name, c.symbol || c.shortName)) continue;
      if (a.market === 'moneyline' && o.type === 'MONEY') rows.push({ value: null, ask: o.ask });
      if (a.market === 'spread' && o.type === 'SPREAD') { const m = /([+-]?\d+(?:\.\d+)?)\s*$/.exec(o.desc || ''); if (m) rows.push({ value: parseFloat(m[1]), ask: o.ask }); }
    }
    const main = rows.slice().sort((x, y) => Math.abs(x.ask - 0.5) - Math.abs(y.ask - 0.5))[0];
    rows.forEach(r => out.push({ book: 'Novig', value: r.value, odds: c2a(r.ask), main: a.market === 'moneyline' || r === main }));
  }
  const kg = kalshiGame(a, g, ctx);
  if (kg) {
    const rows = [];
    if (a.market === 'total') (kg.total || []).forEach(r => { const p = a.side === 'over' ? r.ya : r.na; if (kOK(p)) rows.push({ value: r.strike, p, mid: Math.abs(r.ya - 0.5) }); });
    if (a.market === 'spread') (kg.spread || []).forEach(r => { const mine = kSameA(team, r.team, r.code), p = mine ? r.ya : r.na; if (kOK(p) && kOK(mine ? r.na : r.ya)) rows.push({ value: mine ? -r.strike : r.strike, p, mid: Math.abs(r.ya - 0.5) }); });
    if (a.market === 'moneyline') (kg.game || []).forEach(r => { const p = kSameA(team, r.team, r.code) ? r.ya : r.na; if (kOK(p)) rows.push({ value: null, p, mid: 0 }); });
    const main = rows.slice().sort((x, y) => x.mid - y.mid)[0];
    rows.forEach(r => out.push({ book: 'Kalshi', value: r.value, odds: kAm(r.p), main: a.market === 'moneyline' || r === main }));
  }
  return out;
}
// The best price that meets the target, or null. With no target price, only main lines count (Novig's and Kalshi's alt ladders would always
// reach the number at some price); with a target price, Novig and Kalshi alt lines count too.
function alertMatch(a, g, ctx) {
  const target = a.target === '' ? null : +a.target, odds = a.odds === '' ? null : +a.odds;
  let best = null;
  for (const x of alertOffers(a, g, ctx)) {
    if (odds == null && !x.main) continue;
    if (target != null && a.market !== 'moneyline') {
      if (a.market === 'spread' && !(x.value >= target - 1e-9)) continue;
      if (a.market === 'total' && (a.side === 'over' ? !(x.value <= target + 1e-9) : !(x.value >= target - 1e-9))) continue;
    }
    if (odds != null && alertDec(x.odds) < alertDec(odds) - 1e-9) continue;
    const score = (a.market === 'moneyline' ? 0 : (a.market === 'total' && a.side === 'over' ? -x.value : x.value) * 100) + alertDec(x.odds);
    if (!best || score > best.score) best = Object.assign({ score }, x);
  }
  return best;
}
function checkAlerts() {
  const sh = alertSheet(), rows = alertRows(sh), now = Date.now();
  const active = rows.map((a, i) => Object.assign(a, { row: i + 2 })).filter(a => a.status === 'active');
  if (!active.length) return;
  const boards = {}, ctx = { http: {} };   // league|ET date -> games by id; ctx caches Novig / Kalshi reads for this run
  for (const a of active) {
    const start = new Date(a.start).getTime();
    if (start && now >= start) { sh.getRange(a.row, ALERT_COLS.indexOf('status') + 1).setValue('expired'); continue; }
    const day = Utilities.formatDate(new Date(a.start), 'America/New_York', 'yyyyMMdd'), k = a.league + '|' + day;
    if (!(k in boards)) {
      try {
        const r = UrlFetchApp.fetch('https://api.actionnetwork.com/web/v2/scoreboard/' + a.league + '?bookIds=69,75,49,2988&date=' + day, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
        const j = JSON.parse(r.getContentText()); boards[k] = Object.fromEntries((j.games || []).map(g => [String(g.id), g]));
      } catch (e) { boards[k] = null; PropertiesService.getScriptProperties().setProperty('ALERT_LAST_ERROR', new Date() + ': ' + e); }
    }
    const g = boards[k] && boards[k][String(a.game_id)]; if (!g) continue;
    const m = alertMatch(a, g, ctx); if (!m) continue;
    const line = a.market === 'moneyline' ? '' : (a.market === 'spread' && m.value > 0 ? '+' : a.market === 'total' ? (a.side === 'over' ? 'o' : 'u') : '') + m.value + ' ';
    // (Novig shows its ask with no fee; Kalshi's price includes its trading fee, as in the Line Shop)
    const hit = m.book + ' ' + line + amer(m.odds);
    const ok = ntfy('Line alert: ' + a.label + (a.market === 'moneyline' ? ' ML' : ''), alertText(a) + '\nNow: ' + hit + '\n' + a.game);
    if (ok) { sh.getRange(a.row, ALERT_COLS.indexOf('status') + 1, 1, 3).setValues([['hit', new Date(), hit]]); }
  }
}
function ntfy(title, body) {
  const topic = PropertiesService.getScriptProperties().getProperty('NTFY_TOPIC'); if (!topic) return false;
  const ascii = s => String(s).normalize('NFKD').replace(/[^\x20-\x7E]/g, '');
  const r = UrlFetchApp.fetch('https://ntfy.sh/' + topic, { method: 'post', payload: body, muteHttpExceptions: true,
    headers: { Title: ascii(title), Priority: 'high', Tags: 'rotating_light', Click: LINE_SHOP_URL } });
  return r.getResponseCode() < 300;
}
function setupAlerts() {
  const p = PropertiesService.getScriptProperties();
  let topic = p.getProperty('NTFY_TOPIC');
  if (!topic) { topic = 'aidan-lines-' + Utilities.getUuid().replace(/-/g, '').slice(0, 12); p.setProperty('NTFY_TOPIC', topic); }
  alertSheet();
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'checkAlerts').forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('checkAlerts').timeBased().everyMinutes(5).create();
  ntfy('Line alerts are on', 'You will get a push here when a line reaches one of your targets.');
  Logger.log('Your ntfy topic: ' + topic + '  (in the ntfy app: + > subscribe to this topic). A test alert was just sent.');
}
