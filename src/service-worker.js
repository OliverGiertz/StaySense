const SW_VERSION = "staysense-v1.0.0";
const CORE_CACHE = `${SW_VERSION}-core`;
const RUNTIME_CACHE = `${SW_VERSION}-runtime`;

const CORE_ASSETS = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/pwa.js",
  "/manifest.json",
  "/icons/icon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
  "/vendor/leaflet/leaflet.css",
  "/vendor/leaflet/leaflet.js",
  "/datenschutz.html",
  "/quellen.html",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CORE_CACHE).then((cache) => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CORE_CACHE && key !== RUNTIME_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  const runtime = await caches.open(RUNTIME_CACHE);
  runtime.put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    const runtime = await caches.open(RUNTIME_CACHE);
    runtime.put(request, response.clone());
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw new Error("offline");
  }
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);

  // Cache map tiles and static assets aggressively.
  if (url.pathname.startsWith("/api/map/tile/")) {
    event.respondWith(cacheFirst(event.request));
    return;
  }
  if (url.pathname.startsWith("/vendor/") || url.pathname.endsWith(".css") || url.pathname.endsWith(".js") || url.pathname.endsWith(".svg")) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // Keep score/health API usable in flaky networks.
  if (url.pathname === "/api/health" || url.pathname.startsWith("/api/spot/score")) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // App shell pages: network first with offline fallback.
  if (url.pathname === "/" || url.pathname.endsWith(".html")) {
    event.respondWith(
      networkFirst(event.request).catch(async () => {
        const fallback = await caches.match("/index.html");
        return fallback || new Response("Offline", { status: 503, statusText: "Offline" });
      })
    );
  }
});
