// Network first so updates show up right away; the cached copy keeps the app working when the Wi-Fi drops.
const CACHE = 'dads-voice-v3';
const SHELL = ['./', 'index.html', 'lm.json', 'manifest.webmanifest', 'icon.svg', 'apple-touch-icon.png'];
// Always straight from the network: these say whether a new version or new family settings exist
const LIVE = /\/(version|family)\.json$/;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (LIVE.test(url.pathname)) {
    e.respondWith(fetch(req.url, { cache: 'no-store', credentials: 'same-origin' }).then(res => {
      if (url.pathname.endsWith('family.json') && res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(url.pathname, copy)); }
      return res;
    }).catch(() => caches.match(url.pathname).then(hit => hit || Response.error())));
    return;
  }
  // GitHub Pages lets browsers reuse a file for 10 minutes; no-cache makes the app check for a new version every time it's online
  e.respondWith(
    fetch(req.url, { cache: 'no-cache', credentials: 'same-origin' })
      .then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: true })
        .then(hit => hit || (req.mode === 'navigate' ? caches.match('index.html') : Response.error())))
  );
});
