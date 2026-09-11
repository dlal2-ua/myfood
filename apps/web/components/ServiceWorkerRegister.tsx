"use client";

import { useEffect } from "react";

/** Registra el service worker mínimo (public/sw.js) para que la PWA sea
 * instalable (Fase 2 del roadmap). No hace nada si el navegador no soporta
 * Service Worker (Safari antiguo, navegación en modo privado restringido). */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Instalación no crítica para el funcionamiento de la app — no molesta al usuario.
    });
  }, []);

  return null;
}
