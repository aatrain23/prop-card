// Apps Script for the "CFB Bet Card feed" Google Sheet: lets the Line Shop add a bet row (college football here, UFC to the "UFC Bet Card feed" sheet), the College football page remove one before kickoff,
// and stores / serves SportsLine expert picks in Aidan's private "SportsLine picks (private)" sheet (key required for both).
// Nov 23 2026: also adds / removes NFL player props on the "Props" tab of the "NFL Card feed (props + StackLine)" sheet (sport 'nfl'),
// from the NFL props page's pre-game board, with a "Why this bet" row on "Props Why". Updating: paste this file over the old one
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
                type: d.type, side: d.side, line: d.line === '' ? '' : "'" + d.line, odds: "'" + d.odds, book: d.book, result: '', note: d.note };
    sh.appendRow(head.map(h => (h in v ? v[h] : '')));
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
                units: d.units, result: '', note: d.note };
    sh.appendRow(head.map(h => (h in v ? v[h] : '')));
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
  if (q.action === 'sl') {
    if (q.key !== KEY) return out({ ok: false, error: 'wrong key' });
    const sh = SpreadsheetApp.openById(SL_SHEET_ID).getSheets()[0];
    const last = sh.getLastRow();
    const vals = last >= 2 ? sh.getRange(2, 1, last - 1, SL_COLS.length).getDisplayValues() : [];
    return out({ ok: true, picks: vals.map(r => Object.fromEntries(SL_COLS.map((c, i) => [c, r[i]]))) });
  }
  return out({ ok: true, sheet: SpreadsheetApp.getActive().getName(), ufc: true });
}
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
