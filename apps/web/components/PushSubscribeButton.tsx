"use client";

import { useEffect, useState } from "react";
import { errorMessage } from "@/lib/api";
import { getExistingSubscription, pushSupported, subscribeToPush, unsubscribeFromPush } from "@/lib/push";

/** Activa/desactiva las notificaciones push del navegador actual (sección
 * 10, Fase 3) — condición previa para que cualquier recordatorio (agua,
 * suplementos) pueda llegar realmente al dispositivo. */
export function PushSubscribeButton() {
  const [supported, setSupported] = useState(true);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pushSupported()) {
      setSupported(false);
      return;
    }
    getExistingSubscription().then((sub) => setSubscribed(sub !== null));
  }, []);

  async function onToggle() {
    setBusy(true);
    setError(null);
    try {
      if (subscribed) {
        await unsubscribeFromPush();
        setSubscribed(false);
      } else {
        await subscribeToPush();
        setSubscribed(true);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!supported) {
    return (
      <p className="text-sm text-neutral-500">
        Este navegador no admite notificaciones push.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={onToggle}
        disabled={busy}
        className="self-start rounded-lg border border-neutral-300 px-3 py-2 text-sm disabled:opacity-60 dark:border-neutral-700"
      >
        {subscribed ? "Desactivar notificaciones" : "Activar notificaciones"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
