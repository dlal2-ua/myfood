"use client";

import { AlertTriangle, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import {
  TYPICAL_SECONDS,
  progressFraction,
  progressLabel,
  quotaIsLow,
  quotaLabel,
  resetLabel,
  type AiTask,
} from "@/lib/aiProgress";
import { apiFetch } from "@/lib/api";
import type { AiQuota } from "@/lib/types";

/** Reloj de la espera: un contador por segundo, solo mientras `running`. */
export function useElapsedSeconds(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 250);
    return () => clearInterval(id);
  }, [running]);
  return elapsed;
}

/** Cuánta cuota de iafood le queda hoy al usuario. `reload()` para después de gastar una. */
export function useAiQuota(scope: AiTask): { quota: AiQuota | null; reload: () => void } {
  const [quota, setQuota] = useState<AiQuota | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    apiFetch<AiQuota>(`/api/ai/quota?scope=${scope}`)
      .then((q) => !cancelled && setQuota(q))
      .catch(() => {
        // Saber cuántas quedan es información de apoyo: si falla, la pantalla sigue.
      });
    return () => {
      cancelled = true;
    };
  }, [scope, tick]);
  return { quota, reload: () => setTick((n) => n + 1) };
}

/** Cuántas peticiones quedan hoy, con aviso cuando van quedando pocas. */
export function QuotaBadge({ quota }: { quota: AiQuota | null }) {
  if (!quota) return null;
  const low = quotaIsLow(quota.remaining, quota.limit) || quota.remaining === 0;
  const reset = resetLabel(quota.reset_at);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
        low
          ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
          : "bg-[var(--color-surface-2)] text-[var(--color-muted)]"
      }`}
      title={
        reset
          ? `Cada envío gasta una petición. Se reinician a las ${reset}.`
          : "Cada envío gasta una petición."
      }
    >
      <Sparkles size={13} aria-hidden="true" />
      {quotaLabel(quota.remaining, quota.limit)}
      {quota.instance_remaining != null && quota.instance_remaining < quota.remaining && (
        <span className="font-normal">· {quota.instance_remaining} en casa</span>
      )}
    </span>
  );
}

/** Tres puntos que laten mientras el modelo piensa. */
export function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-current opacity-60"
          style={{ animation: `myfood-dot 1.2s ease-in-out ${i * 0.18}s infinite` }}
        />
      ))}
    </span>
  );
}

/** Lo que se ve mientras se espera una respuesta de iafood: que está pensando, cuánto
 * lleva, cuánto suele faltar y —lo importante— que NO hay que volver a enviarlo.
 *
 * El aviso de no reenviar no es decorativo: la cuota se descuenta al enviar, así que
 * insistir con el mismo texto gasta peticiones del día sin traer ninguna respuesta nueva. */
export function AiWaiting({
  task,
  elapsedSeconds,
  label = "Interpretando lo que has escrito",
}: {
  task: AiTask;
  elapsedSeconds: number;
  label?: string;
}) {
  const typical = TYPICAL_SECONDS[task];
  const fraction = progressFraction(elapsedSeconds, typical);
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3"
    >
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Sparkles size={16} aria-hidden="true" className="text-[var(--color-primary)]" />
        {label}
        <ThinkingDots />
      </p>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface)]"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fraction * 100)}
        aria-label="Progreso de la respuesta"
      >
        <div
          className="h-full rounded-full bg-[var(--color-primary)] transition-[width] duration-300 ease-out"
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      <p className="text-xs text-[var(--color-muted)]">
        {progressLabel(elapsedSeconds, typical)}
      </p>
      <p className="flex items-start gap-1.5 text-xs font-semibold text-amber-800 dark:text-amber-300">
        <AlertTriangle size={14} aria-hidden="true" className="mt-px shrink-0" />
        No lo envíes otra vez: cada envío gasta una de tus peticiones del día, aunque el
        texto sea el mismo. Esta ya está en marcha.
      </p>
    </div>
  );
}
