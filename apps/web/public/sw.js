// Service worker de MyFood (spec §14.4): shell de la app, imágenes de alimentos y búsquedas
// recientes disponibles sin conexión. El resto de la API va siempre directo a red — nada de
// datos nutricionales o de sesión obsoletos. El registro de comidas y agua sin conexión lo
// gestiona la cola de IndexedDB del cliente (lib/offlineQueue.ts), no este fichero.
//
// Las cachés `myfood-pages-*` y `myfood-search-*` contienen datos del usuario (nombre en la
// cabecera, resultados filtrados por sus restricciones): el cliente las borra al entrar y al
// salir (`clearUserCaches`).
const VERSION = "v2";
const SHELL_CACHE = `myfood-shell-${VERSION}`;
const STATIC_CACHE = `myfood-static-${VERSION}`;
const IMAGES_CACHE = `myfood-images-${VERSION}`;
const PAGES_CACHE = `myfood-pages-${VERSION}`;
const SEARCH_CACHE = `myfood-search-${VERSION}`;
const CURRENT_CACHES = [SHELL_CACHE, STATIC_CACHE, IMAGES_CACHE, PAGES_CACHE, SEARCH_CACHE];

const SHELL_ASSETS = ["/manifest.json", "/icon-192.png", "/icon-512.png"];
const IMAGE_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
const IMAGE_MAX_ENTRIES = 300;
const PAGES_MAX_ENTRIES = 60;
const SEARCH_MAX_ENTRIES = 40;

const OFFLINE_HTML = `<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MyFood — sin conexión</title>
<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#1c1917}
</style></head><body><h1>Sin conexión</h1>
<p>Esta página todavía no está guardada en el dispositivo. Vuelve a intentarlo cuando haya red.</p>
<p>Los registros de comida y agua que hagas desde las páginas ya abiertas se guardan y se
sincronizan solos al volver la conexión.</p></body></html>`;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("myfood-") && !CURRENT_CACHES.includes(k))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

async function trim(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - maxEntries)).map((k) => cache.delete(k)));
}

function cacheable(response) {
  return response && response.ok && response.type === "basic" && !response.redirected;
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request, { cacheName });
  if (cached) return cached;
  const response = await fetch(request);
  if (cacheable(response)) {
    const copy = response.clone();
    caches.open(cacheName).then((cache) => cache.put(request, copy));
  }
  return response;
}

// Imágenes de alimentos: CacheFirst 30 días. Solo se guardan las imágenes reales (respuesta
// `immutable`); el placeholder de categoría caduca en una hora en el servidor y no se fija aquí.
async function imageStrategy(request) {
  const cache = await caches.open(IMAGES_CACHE);
  const cached = await cache.match(request);
  if (cached) {
    const storedAt = Number(cached.headers.get("x-sw-cached-at") || 0);
    if (Date.now() - storedAt < IMAGE_MAX_AGE_MS) return cached;
  }
  try {
    const response = await fetch(request);
    const immutable = (response.headers.get("cache-control") || "").includes("immutable");
    if (cacheable(response) && immutable) {
      const headers = new Headers(response.headers);
      headers.set("x-sw-cached-at", String(Date.now()));
      const body = await response.clone().blob();
      await cache.put(request, new Response(body, { status: 200, headers }));
      trim(IMAGES_CACHE, IMAGE_MAX_ENTRIES);
    }
    return response;
  } catch (err) {
    if (cached) return cached;
    throw err;
  }
}

// Páginas y búsquedas: red primero (nunca se sirve algo viejo con conexión) y, si no hay red,
// lo último que se vio. Con las búsquedas esto evita mostrar alimentos que las restricciones
// actuales del usuario excluirían.
async function networkFirst(request, cacheName, maxEntries) {
  try {
    const response = await fetch(request);
    if (cacheable(response)) {
      const copy = response.clone();
      caches.open(cacheName).then((cache) => cache.put(request, copy).then(() => trim(cacheName, maxEntries)));
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request, { cacheName });
    if (cached) return cached;
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  const path = url.pathname;

  if (SHELL_ASSETS.includes(path)) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
    return;
  }
  if (path.startsWith("/_next/static/")) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }
  if (/^\/api\/foods\/[^/]+\/image$/.test(path)) {
    event.respondWith(imageStrategy(request));
    return;
  }
  if (path === "/api/foods/search") {
    event.respondWith(networkFirst(request, SEARCH_CACHE, SEARCH_MAX_ENTRIES));
    return;
  }
  if (path.startsWith("/api/")) return; // el resto de la API, siempre a red

  const isPage = request.mode === "navigate" || request.headers.get("RSC") === "1";
  if (isPage) {
    event.respondWith(
      networkFirst(request, PAGES_CACHE, PAGES_MAX_ENTRIES).catch(() =>
        request.mode === "navigate"
          ? new Response(OFFLINE_HTML, {
              status: 503,
              headers: { "Content-Type": "text/html; charset=utf-8" },
            })
          : Response.error(),
      ),
    );
  }
});

// Web Push autoalojado con VAPID (Fase 3, sección 10) — el payload ya viene
// listo para mostrar (título/cuerpo), lo construye el worker del backend.
self.addEventListener("push", (event) => {
  let payload = { title: "MyFood", body: "Tienes un recordatorio pendiente." };
  if (event.data) {
    try {
      payload = event.data.json();
    } catch {
      payload.body = event.data.text();
    }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow("/"));
});
