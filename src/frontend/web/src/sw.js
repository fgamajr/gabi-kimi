self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open("gabi-shell-v1").then((cache) =>
      cache.addAll([
        "/",
        "/dist/main.js",
        "/dist/index.css",
      ]),
    ),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== "gabi-shell-v1").map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
});
