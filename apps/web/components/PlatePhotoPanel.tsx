"use client";

import { Camera, Images } from "lucide-react";
import { useRef, useState } from "react";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { shrinkImage } from "@/lib/imageResize";
import { DiaryProposalCard } from "@/components/chat/DiaryProposalCard";
import { type AiSession, type MealType, type SmartLogResult } from "@/lib/types";
import { AiWaiting, QuotaBadge, useAiQuota, useElapsedSeconds } from "@/components/ui/AiWaiting";

// 50 × 2s = 100s: el worker corta el análisis a los 80 s, así que con esto sobra margen
// aunque el trabajo espere un rato en la cola.
const MAX_POLL_ATTEMPTS = 50;
const POLL_INTERVAL_MS = 2000;
const MAX_BYTES = 10 * 1024 * 1024;

const pickerClass =
  "inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold has-[:disabled]:opacity-60";

/** Foto del plato → propuesta de diario. Mismo trato que el registro por texto y el chat:
 * Claude estima cada plato entero y lo desglosa en sus ingredientes con sus gramos, el
 * catálogo afina cada ingrediente que reconoce, y el usuario confirma el conjunto. Nada se
 * guarda solo. */
export function PlatePhotoPanel({
  logDate,
  mealType,
  onAdded,
}: {
  logDate: string;
  mealType: MealType;
  onAdded: () => void;
}) {
  const [consent, setConsent] = useState(false);
  const [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [question, setQuestion] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [proposal, setProposal] = useState<SmartLogResult["proposal"]>(null);
  const [deciding, setDeciding] = useState(false);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);
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
            setError("El análisis está tardando más de lo esperado. Vuelve a intentarlo en un momento.");
            resolve();
            return;
          }
          setTimeout(() => void tick(), POLL_INTERVAL_MS);
          return;
        }
        if (session.status !== "succeeded") {
          const failure = session.validation_errors?.[0];
          setError(
            failure?.code === "AI_TIMEOUT"
              ? "El análisis ha tardado demasiado y se ha cortado. Vuelve a intentarlo: no suele repetirse."
              : (failure?.message ?? "No se ha podido analizar la foto."),
          );
          resolve();
          return;
        }
        const payload = session.response_payload as SmartLogResult | null;
        setProposal(payload?.proposal ?? null);
        setQuestion(payload?.pregunta ?? null);
        setWarning(payload?.proposal ? null : (payload?.warning ?? "NO_FOOD_IN_PHOTO"));
        resolve();
      };
      void tick();
    });
  }

  async function onFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    setAnalysing(true);
    setError(null);
    setWarning(null);
    setQuestion(null);
    setNotice(null);
    setProposal(null);
    try {
      // Se reduce aquí, antes de subirla: una foto de móvil entera tarda en subir más de lo
      // que tarda el modelo en mirarla.
      const image = await shrinkImage(file);
      if (image.size > MAX_BYTES) {
        setError("La foto pesa más de 10 MB. Hazla con menos calidad o recórtala.");
        return;
      }
      if (consent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const form = new FormData();
      form.append("image", image, image === file ? file.name : "plato.jpg");
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
      input.value = "";
    }
  }

  /** La propuesta se acepta entera, como en el chat y en el registro por texto. Los platos
   * marcados se guardan además en el catálogo, para reutilizarlos sin volver a estimarlos. */
  async function decide(decision: "approve" | "reject", saveToCatalog: number[]) {
    if (!proposal) return;
    setDeciding(true);
    setError(null);
    try {
      await apiFetch(`/api/ai/proposals/${proposal.ai_proposal_id}/${decision}`, {
        method: "POST",
        ...(decision === "approve"
          ? { body: JSON.stringify({ save_to_catalog: saveToCatalog }) }
          : {}),
      });
      setProposal(null);
      setQuestion(null);
      if (decision === "approve") {
        setNotice(
          saveToCatalog.length > 0
            ? "Apuntado, y guardado en el catálogo."
            : "Apuntado. Si alguna cantidad no cuadra, cámbiala con «Editar» en el diario.",
        );
        onAdded();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeciding(false);
    }
  }

  const disabled = analysing || quota?.remaining === 0;

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
        Hazle una foto a lo que vas a comer. Claude identifica cada plato, lo desglosa en sus
        ingredientes con sus gramos (bocadillo de jamón: pan, jamón, aceite) y afina cada uno
        con el catálogo. Sale mejor con todo a la vista y algo que dé escala al lado — un
        cubierto, un vaso.
      </p>

      <div className="flex flex-wrap gap-2">
        <label
          className={`${pickerClass} bg-[var(--color-primary)] text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)]`}
        >
          <Camera size={18} aria-hidden="true" />
          {analysing ? "Analizando…" : "Hacer una foto"}
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            className="sr-only"
            disabled={disabled}
            onChange={(e) => void onFileSelected(e)}
          />
        </label>
        {/* Sin `capture`: con él, el móvil abre la cámara directamente y no deja elegir una
            foto que ya se hizo. */}
        <label className={`${pickerClass} border border-[var(--color-border-strong)]`}>
          <Images size={18} aria-hidden="true" />
          Elegir de la galería
          <input
            ref={galleryInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            disabled={disabled}
            onChange={(e) => void onFileSelected(e)}
          />
        </label>
      </div>

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
      {notice && (
        <p role="status" className="mt-2 text-sm font-semibold text-[var(--color-primary)]">
          {notice}
        </p>
      )}
      {warning && (
        <p className="mt-2 text-sm text-neutral-500">
          No se ha reconocido comida en esa foto. Prueba con el plato mejor iluminado y de
          frente.
        </p>
      )}
      {question && (
        <p className="mt-2 rounded-[var(--radius-control)] border border-amber-300 bg-amber-50 p-2 text-sm dark:border-amber-800 dark:bg-amber-950">
          <span className="font-medium">Lo que no se ve en la foto: </span>
          {question} Si cambia mucho, ajusta la cantidad con «Editar» después de apuntarlo.
        </p>
      )}

      {proposal && (
        <div className="mt-4">
          <DiaryProposalCard
            key={proposal.ai_proposal_id}
            payload={proposal.payload}
            deciding={deciding}
            onDecide={(decision, saveToCatalog) => void decide(decision, saveToCatalog)}
          />
        </div>
      )}
    </section>
  );
}
