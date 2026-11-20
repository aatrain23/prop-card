// Apps Script for the "CFB Bet Card feed" Google Sheet: lets the Line Shop page add a bet row.
// Setup (once): in the sheet, Extensions > Apps Script, paste this whole file, save, then
// Deploy > New deployment > type "Web app", Execute as "Me", Who has access "Anyone", Deploy, authorize,
// and copy the Web app URL into the Line Shop's "College football card" settings with the key below.
const KEY = 'PASTE-YOUR-KEY-HERE';   // the same key goes into the Line Shop settings; change both if you ever want a new one

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.key !== KEY) return out({ ok: false, error: 'wrong key' });
    const sh = SpreadsheetApp.getActive().getSheets()[0];
    const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
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
function doGet() { return out({ ok: true, sheet: SpreadsheetApp.getActive().getName() }); }
function out(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
