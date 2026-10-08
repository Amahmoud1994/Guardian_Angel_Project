// Guardian Angel — Service Worker
// Handles: install/activate lifecycle, offline caching, Web Push alerts

const CACHE = 'guardian-angel-v3';
const PRECACHE = ['/', '/manifest.json', '/icons/icon-192.png', '/icons/icon-512.png'];

// ── Install: pre-cache app shell ──────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for API, cache-first for assets ─────────────────────
self.addEventListener('fetch', event => {
  const url = event.request.url;
  // Always fetch API calls fresh — never cache them
  if (url.includes('/api/')) return;
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful GET responses
        if (response.ok && url.startsWith(self.location.origin)) {
          const clone = response.clone();
          caches.open(CACHE).then(c => c.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ── Push: show alert notification + relay to foreground page ──────────────────
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}

  const level = data.level || 1;
  const title = data.title || 'Guardian Angel Alert';
  const body  = data.body  || 'Your safety status has changed.';

  const vibrate = {
    1: [200],
    2: [200, 100, 200],
    3: [300, 100, 300, 100, 300],
    4: [400, 100, 400, 100, 400, 100, 400],
  }[level] || [200];

  const icons = {
    1: '/icons/icon-192.png',
    2: '/icons/icon-192.png',
    3: '/icons/icon-192.png',
    4: '/icons/icon-192.png',
  };

  const notifOptions = {
    body,
    icon: icons[level],
    badge: '/icons/icon-72.png',
    vibrate,
    tag: 'guardian-alert',
    renotify: true,
    requireInteraction: true,   // keep it on screen until the user acts on it
    silent: false,
    data: { level, url: '/' },
    actions: level < 4
      ? [{ action: 'checkin', title: 'Check In Now' }]
      : [],
  };

  // Relay push to any open app windows (so foreground popup can trigger)
  const relayToClients = self.clients
    .matchAll({ includeUncontrolled: true, type: 'window' })
    .then(clients => clients.forEach(c => c.postMessage({ type: 'PUSH_ALERT', data })));

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(title, notifOptions),
      relayToClients,
    ])
  );
});

// ── Notification click: open / focus the app ──────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      // Focus an existing window if one is open
      for (const client of clients) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open a new window
      return self.clients.openWindow('/');
    })
  );
});
