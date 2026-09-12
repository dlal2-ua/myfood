"use client";

import { useEffect } from "react";
import { syncLocalNotifications } from "@/lib/localNotifications";

/** Reprograma las notificaciones locales (Capacitor) con las reglas
 * actuales del usuario cada vez que abre la app nativa — no hace nada en
 * el navegador normal (`isNativeApp()` dentro de `syncLocalNotifications`)
 * ni sin sesión iniciada. */
export function LocalNotificationsSync({ authenticated }: { authenticated: boolean }) {
  useEffect(() => {
    if (!authenticated) return;
    syncLocalNotifications().catch(() => {
      // No crítico: si falla, siguen llegando los Web Push de Fase 3.
    });
  }, [authenticated]);

  return null;
}
