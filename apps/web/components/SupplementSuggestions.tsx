"use client";

import { useRef, useState } from "react";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import type { AiSession } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 60;

interface Suggestion {
  proposal_id: string;
  key: string;
  name_es: string;
  dose_amount: number;
  dose_unit: string;
  reason: string;
}

const BLOCKED_MESSAGES: Record<string, string> = {
  SUPPLEMENT_ADVICE_BLOCKED:
    "Con lo que has indicado en tu perfil, MyFood no sugiere suplementos. Consulta a un médico o a un dietista-nutricionista.",
  NOT_ENOUGH_DATA:
    "Registra tus comidas al menos 7 días de los últimos 30 para que se pueda valorar tu ingesta.",
  INSUFFICIENT_MICRONUTRIENT_DATA:
    "Los alimentos que has registrado traen pocos datos de vitaminas y minerales, así que no se puede valorar tu ingesta con fiabilidad.",
};

/** Sugerencia de suplementos con IA (sección 10.7): solo bajo petición explícita, con lista blanca
 * cerrada, dosis puestas por el sistema y aviso obligatorio. Cada una se aprueba o se descarta. */
export function SupplementSuggestions({ onAdded }: { onAdded: () => void }) {
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [disclaimer, setDisclaimer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decided, setDecided] = useState<Record<string, "approved" | "rejected">>({});
  const polls = useRef(0);

  async function poll(sessionId: string): Promise<AiSession | null> {
    polls.current = 0;
    for (;;) {
      polls.current += 1;
      const session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
      if (session.status !== "running") return session;
      if (polls.current >= MAX_POLL_ATTEMPTS) return null;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  async function request() {
    setBusy(true);
    setError(null);
    setSuggestions(null);
    setDecided({});
    try {
      if (consent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const started = await apiFetch<AiSession>("/api/ai/supplement-suggestions", {
        method: "POST",
      });
      const done = await poll(started.id);
      if (!done) {
        setError("La valoración está tardando más de lo esperado. Inténtalo de nuevo.");
      } else if (done.status !== "succeeded") {
        setError("No se ha podido completar la valoración. Inténtalo de nuevo más tarde.");
      } else {
        const payload = done.response_payload as {
          suggestions: Suggestion[];
          disclaimer: string;
        };
        setSuggestions(payload.suggestions);
        setDisclaimer(payload.disclaimer);
      }
    } catch (err) {
      if (err instanceof ApiError && BLOCKED_MESSAGES[err.code]) setError(BLOCKED_MESSAGES[err.code]);
      else if (err instanceof ApiError && err.code === "AI_CONSENT_REQUIRED") {
        setError("Marca la casilla para permitir que tu ingesta agregada se valore con IA.");
      } else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function decide(s: Suggestion, decision: "approve" | "reject") {
    try {
      await apiFetch(`/api/ai/proposals/${s.proposal_id}/${decision}`, { method: "POST" });
      setDecided((prev) => ({
        ...prev,
        [s.proposal_id]: decision === "approve" ? "approved" : "rejected",
      }));
      if (decision === "approve") onAdded();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <h2 className="text-lg font-semibold">¿Te podría convenir algún suplemento?</h2>
      <p className="text-sm text-neutral-500">
        Solo si lo pides: se valora tu ingesta media de los últimos 30 días frente a las referencias y
        se te propone, como mucho, alguno de una lista cerrada. La dosis la pone MyFood; nada se añade
        sin que lo apruebes.
      </p>
      <MedicalDisclaimer>
        Esto no es consejo médico. Si estás embarazada o en lactancia, tienes una patología, tomas
        medicación o eres menor de edad, no se sugieren suplementos: consulta a un profesional.
      </MedicalDisclaimer>
      <label className="flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5"
        />
        Permito que mi ingesta agregada de 30 días (sin datos personales) se valore con Claude.
      </label>
      <button
        type="button"
        onClick={() => void request()}
        disabled={busy}
        className="w-fit rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
      >
        {busy ? "Valorando…" : "Valorar mi ingesta"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {suggestions && suggestions.length === 0 && (
        <p className="text-sm">
          Con tus datos no hay ningún suplemento que se pueda justificar. Eso es un buen resultado.
        </p>
      )}
      {suggestions && suggestions.length > 0 && (
        <ul className="flex flex-col gap-3">
          {suggestions.map((s) => {
            const state = decided[s.proposal_id];
            return (
              <li key={s.proposal_id} className="rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-800">
                <p className="font-medium">
                  {s.name_es} · {s.dose_amount} {s.dose_unit}
                </p>
                <p className="mt-1 text-neutral-600 dark:text-neutral-400">{s.reason}</p>
                {state ? (
                  <p className="mt-2 text-xs text-neutral-500">
                    {state === "approved" ? "Añadido a tus suplementos." : "Descartado."}
                  </p>
                ) : (
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      onClick={() => void decide(s, "approve")}
                      className="rounded-lg bg-[var(--color-primary)] px-3 py-1 text-xs text-white"
                    >
                      Añadir
                    </button>
                    <button
                      type="button"
                      onClick={() => void decide(s, "reject")}
                      className="rounded-lg border border-neutral-300 px-3 py-1 text-xs dark:border-neutral-700"
                    >
                      Descartar
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {disclaimer && suggestions && <p className="text-xs text-neutral-500">{disclaimer}</p>}
    </section>
  );
}
