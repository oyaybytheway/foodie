const CACHE_VERSION = "foodie-v20261110g";
const CACHE_NAME = CACHE_VERSION;
const PRECACHE = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
];
const STATIC_HOSTS = ["unpkg.com"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isHtmlRequest(request) {
  if (request.mode === "navigate") return true;
  const accept = request.headers.get("accept") || "";
  if (accept.includes("text/html")) return true;
  const path = new URL(request.url).pathname;
  return path.endsWith(".html") || path.endsWith("/") || path.endsWith("/foodie");
}

function shouldCache(request, response) {
  if (!response || !response.ok) return false;
  const url = new URL(request.url);
  if (url.origin === self.location.origin) return true;
  return STATIC_HOSTS.some((h) => url.hostname === h || url.hostname.endsWith("." + h));
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // Never cache live lookup APIs
  if (/overpass|nominatim|zippopotam/i.test(url.hostname + url.pathname)) return;

  if (isHtmlRequest(request)) {
    // Network-first for HTML so a new deploy is seen promptly
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (shouldCache(request, res)) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() => caches.match(request).then((r) => r || caches.match("./index.html")))
    );
    return;
  }

  if (url.origin === self.location.origin || STATIC_HOSTS.some((h) => url.hostname === h || url.hostname.endsWith("." + h))) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (shouldCache(request, res)) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() => caches.match(request))
    );
  }
});
