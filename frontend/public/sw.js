/* Code Sonar service worker — minimal app-shell caching.
 * Setup scaffold only: install/update behavior is intentionally conservative.
 * Static same-origin assets are cached on first fetch; API calls always hit
 * the network so scan data is never served stale. */
const CACHE = 'code-sonar-shell-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // API traffic always goes to the network — never cache scan data.
  if (url.pathname.startsWith('/api/')) return;

  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(request).then((hit) => {
        const miss = fetch(request).then((res) => {
          if (res.ok) cache.put(request, res.clone());
          return res;
        });
        return hit || miss;
      })
    )
  );
});
