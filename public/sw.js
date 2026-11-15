const CACHE = 'sc-ani-v3';

// ── Dürtme bildirimleri ──
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (_) {}
  e.waitUntil(
    self.registration.showNotification(data.title || 'Anı Defteri', {
      body: data.body || '💙 Seni düşünüyorum',
      icon: '/icon-192.png',
      badge: '/favicon-32.png',
      tag: 'durt',
      renotify: true,
      vibrate: [80, 60, 80]
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) if ('focus' in c) return c.focus();
      return self.clients.openWindow('/');
    })
  );
});
// Not: '/' ve '/index.html' önceden önbelleğe alınmaz; giriş yapılmamışsa
// bu adresler /login'e yönlenir ve giriş sayfası yanlışlıkla önbelleğe girerdi.
const STATIC = [
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  'https://cdn.tailwindcss.com',
  'https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@1,900&display=swap'
];

// Install: cache all static assets
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting())
  );
});

// Activate: remove old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Yalnızca başarılı, yönlendirilmemiş yanıtlar önbelleğe girer
function cacheable(res) {
  return res && res.ok && !res.redirected && res.type !== 'opaqueredirect';
}

function networkFirst(request) {
  return fetch(request)
    .then(res => {
      // Drive görselleri çapraz kaynaklı (opaque) gelir; çevrimdışı için onları da sakla
      if (cacheable(res) || res.type === 'opaque') {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(request, clone));
      }
      return res;
    })
    .catch(() => caches.match(request));
}

// Fetch strategy:
// - Sayfa geçişleri, API çağrıları ve Drive görselleri: önce ağ (giriş
//   kontrolü sunucuda yapılsın, veri taze kalsın), çevrimdışıysa önbellek
// - Diğer statik dosyalar: önce önbellek
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);

  // Giriş/çıkış asla önbelleğe alınmaz
  if (url.origin === self.location.origin &&
      (url.pathname === '/login' || url.pathname === '/logout')) return;

  if (e.request.mode === 'navigate' ||
      url.pathname.startsWith('/api/') ||
      url.hostname.includes('drive.google.com') ||
      url.hostname.includes('googleusercontent.com')) {
    e.respondWith(networkFirst(e.request));
    return;
  }

  // Cache-first for static assets
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(res => {
        if (!cacheable(res) || res.type === 'opaque') return res;
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      });
    })
  );
});
