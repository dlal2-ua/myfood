"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { WeekLog } from "@/lib/types";

/** Cómo va la semana, de lunes a domingo.
 *
 * Con un objetivo solo diario, cada día es un aprobado o un suspenso — y R10 dice
 * explícitamente que no se haga eso: la investigación sobre apps de dieta encuentra que
 * competir consigo mismo día a día empuja a comer cada vez menos. En una semana, un domingo
 * alto se compensa con el lunes y no hay nada que suspender.
 *
 * Por lo mismo, pasarse no se pinta en rojo ni se llama de ninguna manera: se dice el número y
 * ya. El color de alarma por superar las calorías está prohibido (R10).
 */
const DIAS = ["L", "M", "X", "J", "V", "S", "D"];

export function WeekBudget({ date, reloadKey }: { date: string; reloadKey: number }) {
  const [week, setWeek] = useState<WeekLog | null>(null);

  useEffect(() => {
    let cancelado = false;
    apiFetch<WeekLog>(`/api/log/week?date=${date}`)
      .then((w) => !cancelado && setWeek(w))
      .catch(() => {
        // La semana es contexto: si falla, el día sigue viéndose.
      });
    return () => {
      cancelado = true;
    };
  }, [date, reloadKey]);

  if (!week) return null;
  // Sin nada apuntado en toda la semana no hay nada que contar todavía.
  if (week.total_kcal === 0) return null;

  const objetivoDia = week.target_kcal ? week.target_kcal / 7 : null;
  // La barra se mide contra el objetivo del día para que se vean las diferencias entre días;
  // sin objetivo, contra el día que más suma.
  const escala = objetivoDia ?? Math.max(...week.days.map((d) => d.kcal), 1);
  const restan = week.remaining_kcal;

  return (
    <section
      aria-label="Cómo va la semana"
      className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-card)]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[15px] font-bold">Esta semana</h2>
        <p className="text-sm text-[var(--color-muted)]">
          <span className="font-bold text-[var(--color-text)]">
            {Math.round(week.total_kcal)}
          </span>
          {week.target_kcal != null && <> de {Math.round(week.target_kcal)}</>} kcal
        </p>
      </div>

      <ul className="mt-3 flex items-end justify-between gap-1.5">
        {week.days.map((day, i) => {
          const alto = Math.min(100, (day.kcal / escala) * 100);
          return (
            <li key={day.date} className="flex flex-1 flex-col items-center gap-1">
              <span className="flex h-16 w-full items-end">
                <span
                  aria-hidden="true"
                  className={`w-full rounded-t-[4px] ${
                    day.kcal > 0 ? "bg-[var(--color-primary)]" : "bg-[var(--color-surface-2)]"
                  } ${day.is_past ? "" : "opacity-40"}`}
                  style={{ height: `${Math.max(alto, day.kcal > 0 ? 6 : 3)}%` }}
                />
              </span>
              <span className="text-[11px] font-semibold text-[var(--color-muted)]">
                {DIAS[i]}
              </span>
            </li>
          );
        })}
      </ul>

      {restan != null && (
        <p className="mt-3 text-sm text-[var(--color-muted)]">
          {restan >= 0 ? (
            <>
              Te quedan <span className="font-bold text-[var(--color-text)]">
                {Math.round(restan)} kcal
              </span>{" "}
              para el domingo.
            </>
          ) : (
            <>
              Llevas{" "}
              <span className="font-bold text-[var(--color-text)]">
                {Math.round(-restan)} kcal
              </span>{" "}
              por encima de la semana. Los días que quedan dan de sobra para nivelarlo.
            </>
          )}
        </p>
      )}
    </section>
  );
}
