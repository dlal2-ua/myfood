"use client";

import { useCallback, useEffect, useState } from "react";
import {
  clearQueue,
  flushQueue,
  listQueue,
  onQueueChanged,
  removeItem,
  retryItem,
  type QueueItem,
} from "@/lib/offlineQueue";

const SYNC_INTERVAL_MS = 30_000;

/** Barra de estado de la conexión y de los registros pendientes de sincronizar (spec §14.4).
 * También sincroniza la cola al recuperar la red, al volver a la pestaña y cada 30 s. */
export function OfflineSync({ userId }: { userId: string | null }) {
  const [online, setOnline] = useState(true);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [needsLogin, setNeedsLogin] = useState(false);

  const refresh = useCallback(async () => {
    if (!userId) {
      setItems([]);
      return;
    }
    try {
      setItems(await listQueue(userId));
    } catch {
      setItems([]);
    }
  }, [userId]);

  const sync = useCallback(async () => {
    if (!userId || !navigator.onLine) return;
    setSyncing(true);
    try {
      const res = await flushQueue(userId);
      setNeedsLogin(res.needsLogin);
    } catch {
      // IndexedDB no disponible: no hay cola que sincronizar.
    } finally {
      setSyncing(false);
      await refresh();
    }
  }, [userId, refresh]);

  useEffect(() => {
    setOnline(navigator.onLine);
    const goOnline = () => {
      setOnline(true);
      void sync();
    };
    const goOffline = () => setOnline(false);
    const onVisible = () => {
      if (document.visibilityState === "visible") void sync();
    };
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    document.addEventListener("visibilitychange", onVisible);
    const stop = onQueueChanged(() => void refresh());
    const timer = window.setInterval(() => void sync(), SYNC_INTERVAL_MS);
    void refresh().then(() => sync());
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      document.removeEventListener("visibilitychange", onVisible);
      stop();
      window.clearInterval(timer);
    };
  }, [refresh, sync]);

  if (!userId) return null;
  const pending = items.filter((i) => i.status === "pending");
  const rejected = items.filter((i) => i.status === "rejected");
  if (online && items.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="border-b border-amber-300 bg-amber-50 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-2 px-4 py-2">
        {!online && (
          <p>
            Sin conexión. Puedes seguir registrando comidas y agua: se guardan en este dispositivo y
            se sincronizan solos al volver la red.
          </p>
        )}
        {needsLogin && (
          <p>Tu sesión ha caducado: vuelve a entrar para sincronizar los registros pendientes.</p>
        )}
        {pending.length > 0 && (
          <p className="flex flex-wrap items-center gap-2">
            <span>
              {pending.length === 1
                ? "1 registro pendiente de sincronizar"
                : `${pending.length} registros pendientes de sincronizar`}
              {" — todavía no cuentan en tus totales."}
            </span>
            {online && (
              <button
                type="button"
                onClick={() => void sync()}
                disabled={syncing}
                className="rounded border border-amber-400 px-2 py-0.5 disabled:opacity-60"
              >
                {syncing ? "Sincronizando…" : "Sincronizar ahora"}
              </button>
            )}
          </p>
        )}
        {items.length > 0 && (
          <details>
            <summary className="cursor-pointer">Ver pendientes</summary>
            <ul className="mt-1 flex flex-col gap-1">
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-2">
                  <span>
                    {item.label}
                    {item.status === "rejected" && (
                      <span className="text-red-700 dark:text-red-300">
                        {" "}
                        — rechazado: {item.error}
                      </span>
                    )}
                  </span>
                  {item.status === "rejected" && (
                    <button type="button" className="underline" onClick={() => void retryItem(item.id)}>
                      Reintentar
                    </button>
                  )}
                  <button type="button" className="underline" onClick={() => void removeItem(item.id)}>
                    Descartar
                  </button>
                </li>
              ))}
            </ul>
            {rejected.length > 1 && (
              <button
                type="button"
                className="mt-1 underline"
                onClick={() => void clearQueue(userId)}
              >
                Descartar todos
              </button>
            )}
          </details>
        )}
      </div>
    </div>
  );
}
