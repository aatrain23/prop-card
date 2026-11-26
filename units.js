// Units only (Aidan, Nov 25 2026): bet pages never show how much a bet is in dollars, only units.
// Any "$12.34" in the page's text (bet notes, "Why this bet", grades) is shown as units instead.
// The page's unit size comes from this script tag's data-unit (dollars per unit), or window.BET_UNIT if the page sets it.
(function () {
  const tag = document.currentScript, base = +(tag && tag.dataset.unit) || 100;
  const unit = () => +window.BET_UNIT || base;
  const RX = /([+\-−]?)\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(\s?[kK]\b)?/g;
  const conv = s => s.replace(RX, (m, sg, n, k) => {
    const v = parseFloat(n.replace(/,/g, '')) * (k ? 1000 : 1) / unit();
    return sg + (Math.round(v * 100 + 1e-9) / 100).toFixed(2) + 'u';
  }).replace(/\b(\d+(?:\.\d+)?u) (?:a|per) unit\b/gi, '').replace(/\b1 unit = 1\.00u\.?\s*/gi, '').replace(/\s*\(\s*\)/g, '').replace(/ {2,}/g, ' ');
  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'NOSCRIPT']);
  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { if (root.nodeValue.includes('$')) { const p = root.parentElement; if (p && !SKIP.has(p.tagName) && !p.closest('[data-keep-dollars]')) { const v = conv(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; } } return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1 && (SKIP.has(root.tagName) || root.hasAttribute('data-keep-dollars'))) return;
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const list = []; while (tw.nextNode()) if (tw.currentNode.nodeValue.includes('$')) list.push(tw.currentNode);
    list.forEach(walk);
  }
  window.toUnits = conv;
  const start = () => {
    walk(document.body);
    new MutationObserver(ms => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); else m.addedNodes.forEach(walk); } })
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
