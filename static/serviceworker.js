const CACHE_NAME = 'omnistock-pwa-v1';
const STATIC_ASSETS = [
  '/',
  '/pos/',
  '/inventory/',
  '/accounts/login/',
  '/static/manifest.json',
  '/offline/',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Pre-caching static offline assets');
      return cache.addAll(STATIC_ASSETS).catch(err => console.log('Precache error:', err));
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(
        keyList.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[ServiceWorker] Removing old cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return;
  }

  // Network first with cache fallback strategy for real-time stock freshness
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            // Only cache internal and CDN assets
            if (event.request.url.startsWith(self.location.origin) || event.request.url.includes('cdn.jsdelivr.net')) {
              cache.put(event.request, responseToCache);
            }
          });
        }
        return networkResponse;
      })
      .catch(async () => {
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }
        // If HTML page request fails and not cached, return offline fallback page
        if (event.request.mode === 'navigate') {
          return caches.match('/offline/');
        }
      })
  );
});
