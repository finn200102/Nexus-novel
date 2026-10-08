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

// Web Push: the server sends {title, body, url, tag}. Notifications with the
// same tag replace each other, so one story shows its newest update.
self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "" };
  }
  const title = typeof payload.title === "string" && payload.title ? payload.title : "Nexus Novel";
  const options = {
    body: typeof payload.body === "string" ? payload.body : "",
    tag: typeof payload.tag === "string" ? payload.tag : undefined,
    data: { url: typeof payload.url === "string" ? payload.url : "/" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const requested = (event.notification.data && event.notification.data.url) || "/";
  // Only same-origin paths are opened, whatever the payload says.
  const target = new URL(requested, self.location.origin);
  const url = target.origin === self.location.origin ? target.href : self.location.origin + "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((client) => "focus" in client);
      if (existing) {
        return existing.navigate(url).catch(() => null).then((client) => (client || existing).focus());
      }
      return self.clients.openWindow(url);
    })
  );
});
