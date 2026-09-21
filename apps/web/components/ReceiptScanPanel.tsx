"use client";

import { useRef, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { AiSession, ReceiptScanItem, ReceiptScanResult } from "@/lib/types";

const MAX_POLL_ATTEMPTS = 30; // 30 × 2s = 60s
const POLL_INTERVAL_MS = 2000;

interface ReviewItem extends ReceiptScanItem {
  quantityInput: string;
}

export function ReceiptScanPanel({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [consent, setConsent] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [addingIndex, setAddingIndex] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollCountRef = useRef(0);

  async function pollSession(sessionId: string) {
    pollCountRef.current = 0;
    const tick = async (): Promise<void> => {
      pollCountRef.current += 1;
      let session: AiSession;
      try {
        session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
      } catch (err) {
        setError(errorMessage(err));
        return;
      }
      if (session.status === "running") {
        if (pollCountRef.current >= MAX_POLL_ATTEMPTS) {
          setError("El escaneo está tardando más de lo esperado. Inténtalo de nuevo.");
          return;
        }
        setTimeout(() => void tick(), POLL_INTERVAL_MS);
        return;
      }
      if (session.status !== "succeeded") {
        setError(session.validation_errors?.[0]?.message ?? "No se ha podido leer el ticket.");
        return;
      }
      const payload = session.response_payload as unknown as ReceiptScanResult | null;
      const items = payload?.items ?? [];
      setReviewItems(items.map((item) => ({ ...item, quantityInput: String(item.grams) })));
      if (items.length === 0) {
        setError("No se ha reconocido ningún alimento en el ticket.");
      }
    };
    await tick();
  }

  async function onFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setScanning(true);
    setError(null);
    setReviewItems([]);
    try {
      if (consent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const form = new FormData();
      form.append("file", file);
      const session = await apiFetch<AiSession>("/api/receipts/scan", {
        method: "POST",
        body: form,
      });
      await pollSession(session.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setScanning(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function updateItem(index: number, quantityInput: string) {
    setReviewItems((prev) => prev.map((item, i) => (i === index ? { ...item, quantityInput } : item)));
  }

  function discardItem(index: number) {
    setReviewItems((prev) => prev.filter((_, i) => i !== index));
  }

  async function confirmItem(index: number) {
    const item = reviewItems[index];
    setAddingIndex(index);
    setError(null);
    try {
      await apiFetch("/api/pantry", {
        method: "POST",
        body: JSON.stringify({
          food_id: item.food_id,
          quantity_g: Number(item.quantityInput),
        }),
      });
      discardItem(index);
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAddingIndex(null);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="text-lg font-semibold">Escanear ticket de compra</span>
        <span className="text-neutral-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <>
          <p className="text-sm text-neutral-500">
            Sube una foto del ticket — se reconoce el texto y se proponen los alimentos que
            aparecen, para revisar antes de añadirlos a la despensa.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            Acepto que el texto del ticket se envíe a iafood para interpretarlo
          </label>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            onChange={onFileSelected}
            disabled={scanning || !consent}
            className="text-sm"
          />
          {scanning && <p className="text-sm text-neutral-500">Leyendo el ticket…</p>}
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

          {reviewItems.length > 0 && (
            <ul className="mt-2 flex flex-col gap-3">
              {reviewItems.map((item, index) => (
                <li
                  key={`${item.food_id}-${index}`}
                  className="flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3 text-sm dark:border-neutral-700"
                >
                  <div className="flex-1">
                    <p className="font-medium">{item.name_es}</p>
                    <p className="text-xs text-neutral-400">
                      Del ticket: &ldquo;{item.original_line}&rdquo;
                    </p>
                  </div>
                  <input
                    type="number"
                    min={1}
                    value={item.quantityInput}
                    onChange={(e) => updateItem(index, e.target.value)}
                    className="w-24 rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-2 py-1"
                  />
                  <span className="text-xs text-neutral-400">g</span>
                  <button
                    type="button"
                    onClick={() => confirmItem(index)}
                    disabled={addingIndex === index}
                    className="rounded-full bg-[var(--color-primary)] px-3 py-1 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
                  >
                    {addingIndex === index ? "Añadiendo…" : "Añadir"}
                  </button>
                  <button
                    type="button"
                    onClick={() => discardItem(index)}
                    className="text-neutral-400 underline"
                  >
                    Descartar
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
