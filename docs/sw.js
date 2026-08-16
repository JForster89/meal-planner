// Cache the list so it opens in a supermarket dead spot.
var CACHE = 'shopping-20260816233744';
var ASSETS = ['./', './index.html', './cook.html', './manifest.json', './icon.svg', './img/088159ecccb86614.jpg', './img/247051050ac9062f.jpg', './img/3a414dba654d9b9f.jpg', './img/48b42d94e75e11cb.jpg', './img/4db0aaa59e637aab.jpg', './img/5bd7012772b41b2c.jpg', './img/6166a0c927e30be2.jpg', './img/6e1c8da292e48b8e.jpg', './img/73c6f4f6aec4038b.jpg', './img/7ed1045b4bff6300.jpg', './img/c4655151fd4569d5.jpg', './img/d98a4a73e38cf54f.jpg'];

self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(ASSETS); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

// Network first so a republished list is picked up, falling back to the cached
// copy when there's no signal.
self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(function (res) {
      var copy = res.clone();
      caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
      return res;
    }).catch(function () {
      return caches.match(e.request).then(function (hit) {
        return hit || caches.match('./index.html');
      });
    })
  );
});
