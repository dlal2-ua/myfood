"use client";

import { useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";

/** El consentimiento para usar la IA, pedido solo cuando hace falta.
 *
 * Antes cada panel llevaba una casilla fija de «acepto que esto se envíe a Claude», que
 * quien ya había aceptado —casi todo el mundo, desde el primer día— seguía viendo siempre.
 * Ahora no se enseña nada hasta que el servidor dice que falta (`AI_CONSENT_REQUIRED`); al
 * aceptarlo se guarda y se repite lo que se estaba haciendo. */
export function AiConsentPrompt({
  what,
  onAccepted,
}: {
  /** Qué se va a enviar: «este texto», «esta foto». */
  what: string;
  onAccepted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/consents", {
        method: "POST",
        body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
      });
      onAccepted();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-sm shadow-[var(--shadow-card)]">
      <p className="mb-2">
        Para interpretarlo hay que enviar {what} a Claude, sin tu nombre ni datos que te
        identifiquen. Solo te lo preguntamos una vez.
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={() => void accept()}
        className="rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] disabled:opacity-60"
      >
        {busy ? "Guardando…" : "Aceptar y continuar"}
      </button>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
