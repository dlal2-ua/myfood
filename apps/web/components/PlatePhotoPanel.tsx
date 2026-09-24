"use client";

import { Camera } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { submitOrQueue } from "@/lib/offlineQueue";
import { DiaryProposalCard } from "@/components/chat/DiaryProposalCard";
import { describeInterpretation, ORIGIN_LABELS } from "@/lib/smartLog";
import {
  MEAL_TYPE_LABELS,
  MEAL_TYPES,
  type AiSession,
  type MealType,
  type SmartLogItem,
  type SmartLogResult,
} from "@/lib/types";
import {
  AiWaiting,
  QuotaBadge,
  ThinkingDots,
  useAiQuota,
  useElapsedSeconds,
} from "@/components/ui/AiWaiting";

// 60 × 2s = 120s: son dos llamadas al modelo, y una tercera si algo del plato no está en
// el catálogo y se busca en internet.
const MAX_POLL_ATTEMPTS = 60;
const POLL_INTERVAL_MS = 2000;
const MAX_BYTES = 10 * 1024 * 1024;

interface ReviewItem extends SmartLogItem {
  gramsInput: string;
  mealType: MealType;
}

/** Foto del plato → alimentos propuestos. Mismo trato que el registro por texto: Claude
 * propone, el usuario revisa las cantidades y confirma una a una. Nada se guarda solo. */
export function PlatePhotoPanel({
  userId,
  logDate,
  mealType,
  onAdded,
}: {
  userId: string;
  logDate: string;
  mealType: MealType;
  onAdded: () => void;
}) {
  const [consent, setConsent] = useState(false);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [question, setQuestion] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[]>([]);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [confirmingIndex, setConfirmingIndex] = useState<number | null>(null);
  const [webProposal, setWebProposal] = useState<SmartLogResult["proposal"]>(null);
  const [webDeciding, setWebDeciding] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollCountRef = useRef(0);
  const elapsed = useElapsedSeconds(analysing);
  const { quota, reload: reloadQuota } = useAiQuota("plate_photo");

  function pollSession(sessionId: string): Promise<void> {
    pollCountRef.current = 0;
    return new Promise<void>((resolve) => {
      const tick = async () => {
        pollCountRef.current += 1;
        let session: AiSession;
        try {
          session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
        } catch (err) {
          setError(errorMessage(err));
          resolve();
          return;
        }
        if (session.status === "running") {
          if (pollCountRef.current >= MAX_POLL_ATTEMPTS) {
            setError(
              "El análisis está tardando más de lo esperado. Vuelve a entrar en un momento: " +
                "si termina, lo verás aquí sin gastar otra petición.",
            );
            resolve();
            return;
          }
          setTimeout(() => void tick(), POLL_INTERVAL_MS);
          return;
        }
        if (session.status !== "succeeded") {
          setError(
            session.validation_errors?.[0]?.message ?? "No se ha podido analizar la foto.",
          );
          resolve();
          return;
        }
        const payload = session.response_payload as SmartLogResult | null;
        const found = payload?.items ?? [];
        setItems(
          found.map((item) => ({ ...item, gramsInput: String(item.grams), mealType })),
        );
        setWarning(found.length === 0 ? (payload?.warning ?? "NO_MATCH") : null);
        setQuestion(payload?.pregunta ?? null);
        setMissing(payload?.no_encontrados ?? []);
        setWebProposal(payload?.proposal ?? null);
        resolve();
      };
      void tick();
    });
  }

  async function onFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError("La foto pesa más de 10 MB. Hazla con menos calidad o recórtala.");
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setAnalysing(true);
    setError(null);
    setWarning(null);
    setQuestion(null);
    setMissing([]);
    setWebProposal(null);
    setItems([]);
    try {
      if (consent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const form = new FormData();
      form.append("image", file);
      form.append("log_date", logDate);
      form.append("meal_type", mealType);
      const session = await apiFetch<AiSession>("/api/log/photo", {
        method: "POST",
        body: form,
      });
      await pollSession(session.id);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? `${err.message} Se reinician a las 00:00.`
          : errorMessage(err),
      );
    } finally {
      setAnalysing(false);
      reloadQuota();
      // Para poder volver a elegir la MISMA foto si algo falló.
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  /** La propuesta del respaldo web se acepta entera, como la del chat: son valores estimados
   * que no vienen del catálogo, así que se enseñan juntos con su fuente y se confirman de una
   * vez en vez de línea a línea. */
  async function decideWebProposal(decision: "approve" | "reject") {
    const proposal = webProposal;
    if (!proposal) return;
    setWebDeciding(true);
    try {
      await apiFetch(`/api/ai/proposals/${proposal.ai_proposal_id}/${decision}`, {
        method: "POST",
      });
      setWebProposal(null);
      if (decision === "approve") onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setWebDeciding(false);
    }
  }

  function updateItem(index: number, patch: Partial<ReviewItem>) {
    setItems((prev) => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  function discardItem(index: number) {
    setItems((prev) => prev.filter((_, i) => i !== index));
  }

  async function confirmItem(index: number) {
    const item = items[index];
    setConfirmingIndex(index);
    setError(null);
    try {
      await submitOrQueue({
        userId,
        kind: "food",
        label: `${item.name_es} — ${Number(item.gramsInput)} g (${MEAL_TYPE_LABELS[item.mealType]}, ${logDate})`,
        payload: {
          log_date: logDate,
          meal_type: item.mealType,
          food_id: item.food_id,
          grams: Number(item.gramsInput),
        },
      });
      discardItem(index);
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setConfirmingIndex(null);
    }
  }

  const inputClass =
    "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

  return (
    <section
      id="foto"
      className="scroll-mt-20 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Foto del plato</h2>
        <QuotaBadge quota={quota} />
      </div>
      <p className="mb-3 text-sm text-neutral-500">
        Hazle una foto a lo que vas a comer y Claude dice qué alimentos ve y en qué cantidad;
        las calorías salen del catálogo. Sale mejor con el plato entero a la vista y algo que
        dé escala al lado — un cubierto, un vaso.
      </p>

      <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] has-[:disabled]:opacity-60">
        <Camera size={18} aria-hidden="true" />
        {analysing ? "Analizando…" : "Hacer o elegir una foto"}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          className="sr-only"
          disabled={analysing || quota?.remaining === 0}
          onChange={(e) => void onFileSelected(e)}
        />
      </label>

      <label className="mt-2 flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5"
          disabled={analysing}
        />
        Acepto que esta foto (sin mi nombre ni datos identificativos) se envíe a Claude para
        interpretarla. No se guarda: se borra en cuanto se ha analizado.
      </label>

      <p className="mt-2 text-xs text-neutral-500">
        Lo que sale de una foto es una estimación: repasa las cantidades antes de guardar.
      </p>

      {analysing && (
        <div className="mt-3">
          <AiWaiting task="plate_photo" elapsedSeconds={elapsed} label="Mirando el plato" />
        </div>
      )}
      {!analysing && quota?.remaining === 0 && (
        <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">
          Has gastado tus {quota.limit} fotos de hoy. Vuelven a las 00:00 — mientras tanto
          puedes registrar escribiendo o buscando el alimento.
        </p>
      )}
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {warning === "NO_FOOD_IN_PHOTO" && (
        <p className="mt-2 text-sm text-neutral-500">
          No se ha reconocido comida en esa foto. Prueba con el plato mejor iluminado y de
          frente.
        </p>
      )}
      {warning === "NO_MATCH" && (
        <p className="mt-2 text-sm text-neutral-500">
          Se ha visto comida, pero no hay nada parecido en el catálogo para proponerte.
        </p>
      )}
      {question && (
        <p className="mt-2 rounded-[var(--radius-control)] border border-amber-300 bg-amber-50 p-2 text-sm dark:border-amber-800 dark:bg-amber-950">
          <span className="font-medium">Para afinar: </span>
          {question} Ajusta los gramos a mano aquí abajo si hace falta.
        </p>
      )}
      {/* Si el respaldo web ya lo ha resuelto, mandar al chat sobra: ya está propuesto. */}
      {missing.length > 0 && !webProposal && (
        <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
          No está en el catálogo: <span className="font-medium">{missing.join(", ")}</span>.{" "}
          <Link href="/chat" className="underline">
            Díselo al chat
          </Link>{" "}
          — ese sí sabe estimar un plato que no tenemos fichado.
        </p>
      )}

      {webProposal && (
        <div className="mt-4">
          <p className="mb-2 text-sm text-neutral-600 dark:text-neutral-400">
            Esto no estaba en el catálogo, así que se ha buscado en internet. Los valores son
            una estimación y se apuntan marcados como tal:
          </p>
          <DiaryProposalCard
            payload={webProposal.payload}
            deciding={webDeciding}
            onDecide={(decision) => void decideWebProposal(decision)}
          />
        </div>
      )}

      {items.length > 0 && (
        <div className="mt-4 flex flex-col gap-3">
          {items.map((item, index) => (
            <div
              key={`${item.food_id}-${index}`}
              className="flex flex-wrap items-end gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3"
            >
              <div className="min-w-[12rem] flex-1">
                <p className="text-sm font-medium">{item.name_es}</p>
                <p className="text-xs text-neutral-500">
                  &quot;{item.approx_quantity_text}&quot;
                  {describeInterpretation(item) && <> · {describeInterpretation(item)}</>}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {item.origen && item.origen !== "desconocido" && (
                    <span className="rounded-full bg-[var(--color-primary-soft)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary)]">
                      {ORIGIN_LABELS[item.origen]}
                    </span>
                  )}
                  {item.confianza === "baja" && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                      poco seguro
                    </span>
                  )}
                </div>
                {item.motivo && <p className="mt-1 text-xs text-neutral-500">{item.motivo}</p>}
              </div>
              <label className="flex flex-col gap-1 text-sm">
                Comida
                <select
                  className={inputClass}
                  value={item.mealType}
                  onChange={(e) => updateItem(index, { mealType: e.target.value as MealType })}
                >
                  {MEAL_TYPES.map((mt) => (
                    <option key={mt} value={mt}>
                      {MEAL_TYPE_LABELS[mt]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Gramos
                <input
                  type="number"
                  min={1}
                  max={5000}
                  className={inputClass}
                  value={item.gramsInput}
                  onChange={(e) => updateItem(index, { gramsInput: e.target.value })}
                />
              </label>
              <button
                type="button"
                disabled={confirmingIndex === index}
                onClick={() => void confirmItem(index)}
                className="inline-flex items-center gap-2 rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] disabled:opacity-60"
              >
                {confirmingIndex === index && <ThinkingDots />}
                Confirmar
              </button>
              <button
                type="button"
                onClick={() => discardItem(index)}
                className="text-sm text-neutral-500 underline"
              >
                Descartar
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
