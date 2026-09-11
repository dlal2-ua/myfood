// Service worker mínimo — solo lo necesario para que la PWA sea instalable
// (sección "Notificaciones push" / roadmap Fase 2, "PWA con html5-qrcode").
// La app es casi toda contenido dinámico autenticado por usuario, así que
// deliberadamente NO se cachea nada de red — evita servir datos nutricionales
// o de sesión obsoletos. Solo cachea el icono/manifest (estáticos, sin datos
// de usuario) para que quede algo que mostrar si el móvil abre la app sin red.
const CACHE_NAME = "myfood-shell-v1";
const SHELL_ASSETS = ["/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (!SHELL_ASSETS.includes(url.pathname)) return; // todo lo demás va directo a red

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
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
