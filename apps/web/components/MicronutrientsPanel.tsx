"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { MicronutrientsDay } from "@/lib/types";

/** Barra de progreso neutra — nunca roja, nunca "objetivo cumplido/fallado"
 * (mismo criterio ético que el resto de la gamificación, R10): superar el
 * 100% de un micronutriente no es un problema visual, solo información. */
function Bar({ pct }: { pct: number }) {
  const width = Math.min(pct, 100);
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
      <div className="h-full bg-[var(--color-primary)]" style={{ width: `${width}%` }} />
    </div>
  );
}

export function MicronutrientsPanel({ date }: { date: string }) {
  const [data, setData] = useState<MicronutrientsDay | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    apiFetch<MicronutrientsDay>(`/api/log/micronutrients?date=${date}`)
      .then(setData)
      .catch(() => setData(null));
  }, [date]);

  if (!data) return null;

  return (
    <div className="mt-4 rounded-lg border border-neutral-200 p-4 text-sm dark:border-neutral-800">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="font-semibold">Micronutrientes de hoy</span>
        <span className="text-neutral-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <>
          <p className="mt-2 text-xs text-neutral-500">
            Comparado con valores de referencia poblacionales (EFSA) — orientativo, no un
            objetivo médico individual.
          </p>
          <ul className="mt-3 flex flex-col gap-3">
            {data.nutrients.map((n) => (
              <li key={n.key}>
                <div className="mb-1 flex justify-between text-xs text-neutral-500">
                  <span>{n.label}</span>
                  <span>
                    {n.amount} / {n.reference} {n.unit} ({n.pct_of_reference}%)
                  </span>
                </div>
                <Bar pct={n.pct_of_reference} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
