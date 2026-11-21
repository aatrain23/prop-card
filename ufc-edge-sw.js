// Octagon Edge (ufc-edge.html as an app): network-first so picks and fight night are always fresh; the last copy opens offline.
const C = 'octagon-edge-v1';
const SHELL = ['ufc-edge.html', 'ufc-edge.webmanifest', 'octagon-edge-icon.svg', 'octagon-edge-icon-192.png', 'octagon-edge-icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(C).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== C).map(x => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;   // live ESPN / Polymarket / X data always go to the network
  const key = u.origin + u.pathname;
  e.respondWith(fetch(e.request).then(r => { if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put(key, cp)); } return r; })
    .catch(() => caches.match(key).then(m => m || caches.match(new URL('ufc-edge.html', location.href).href))));
});
