/* Himuda Housing Colony Sanyard PWA service worker — network-first so phones get updates */
const CACHE = 'hbc-sanyard-v119-campaign-refresh';
const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.webmanifest?v=20260810pwa1',
  '/apple-touch-icon.png?v=20260810pwa1',
  '/portal.css?v=20260811campaigns2',
  '/portal.js?v=20260811campaigns2',
  '/assets/favicon-192.png?v=20260810pwa1',
  '/assets/apple-touch-icon.png?v=20260810pwa1',
  '/assets/hbcs-sanyard-seal-512.png?v=20260810pwa1',
  '/assets/hbcs-sanyard-seal-512-maskable.png?v=20260810pwa1',
  '/assets/mhws-logo/mhws-logo-web-512.webp',
  '/assets/mhws-logo/mhws-logo-web-512.png',
  '/assets/mhws-logo/mhws-logo-web-256.webp',
  '/assets/mhws-logo/mhws-logo-web-256.png',
  '/assets/rwa-assistant-avatar.svg',
  '/assets/hbcs-sanyard-seal-240.webp',
  '/assets/hbcs-sanyard-seal-240.jpg',
  '/assets/hbcs-sanyard-seal-mark.jpg',
  '/assets/og-share-card.jpg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_e) {
    data = { body: event.data ? event.data.text() : '' };
  }
  const title = data.title || 'Himuda Housing Colony Sanyard';
  const options = {
    body: data.body || 'New update',
    icon: '/assets/favicon-192.png?v=20260810pwa1',
    badge: '/assets/favicon-192.png?v=20260810pwa1',
    data: { url: data.url || '/' },
    tag: data.eventType || 'rwa',
    renotify: true,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  const url = new URL(target, self.location.origin).href;
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.startsWith(self.location.origin) && 'focus' in client) {
          return client.focus().then(() => {
            if ('navigate' in client) return client.navigate(url);
            return undefined;
          });
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
      return undefined;
    })
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/admin')) {
    return;
  }

  // Share/OG cards must never be rewritten to the app shell — WhatsApp + browsers
  // need the real HTML + image assets.
  if (url.pathname.startsWith('/share/') || url.pathname.startsWith('/s/')) {
    event.respondWith(fetch(req));
    return;
  }

  // HTML + JS/CSS: network-first so updates land without stale cache
  const path = url.pathname;
  const isNavigate = req.mode === 'navigate';
  const isAppShell = /\.(?:js|css)(?:$|\?)/.test(path) || path.endsWith('manifest.webmanifest');
  const isHtmlDoc = isNavigate || path === '/' || path.endsWith('.html') || path.endsWith('/index.html');
  if (isHtmlDoc || isAppShell) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            // Only the app shell maps to /index.html — never overwrite it with other HTML.
            const key = (isNavigate && (path === '/' || path === '/index.html')) ? '/index.html' : req;
            caches.open(CACHE).then((cache) => cache.put(key, copy));
          }
          return res;
        })
        .catch(() => caches.match(isNavigate ? '/index.html' : req))
    );
    return;
  }

  // Other static assets: stale-while-revalidate
  event.respondWith(
    caches.match(req).then((hit) => {
      const fetching = fetch(req).then((res) => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || fetching;
    })
  );
});
