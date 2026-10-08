const CACHE = "nexus-shell-v3";
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(["/", "/manifest.webmanifest"])));
  self.skipWaiting();
});
self.addEventListener("activate", (event) => event.waitUntil(
  caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
    .then(() => self.clients.claim())
));
function remember(request, response) {
  if (response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }
  // Hashed bundles never change, so the app can boot offline once visited.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((res) => remember(request, res))));
    return;
  }
  // Client-side routes all render index.html; keep the newest copy for offline.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => remember("/", res))
        .catch(() => caches.match("/"))
    );
    return;
  }
  event.respondWith(fetch(request).then((res) => remember(request, res)).catch(() => caches.match(request)));
});
