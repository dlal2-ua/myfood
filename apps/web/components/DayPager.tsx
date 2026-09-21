"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { localDateIso } from "@/lib/dates";
import { relativeDayLabel, shiftIsoDate } from "@/lib/dayNav";

/** Selector de día del Diario: anterior / siguiente, «Hoy», «Ayer» o la fecha, y un calendario para
 * saltar a cualquier día. No deja pasar de mañana: no se registra lo que aún no se ha comido. */
export function DayPager({ date, onChange }: { date: string; onChange: (iso: string) => void }) {
  const today = localDateIso();
  const round =
    "grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-surface)] transition-colors hover:border-[var(--color-primary)] disabled:opacity-40";

  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={() => onChange(shiftIsoDate(date, -1))} aria-label="Día anterior" className={round}>
        <ChevronLeft size={20} aria-hidden="true" />
      </button>
      <div className="relative">
        <span
          aria-hidden="true"
          className="flex min-h-10 min-w-32 items-center justify-center gap-2 rounded-full border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-4 text-sm font-bold capitalize"
        >
          <CalendarDays size={16} className="text-[var(--color-primary)]" />
          {relativeDayLabel(date, today)}
        </span>
        {/* El selector nativo va encima, invisible: tocar la etiqueta abre el calendario en cualquier navegador. */}
        <input
          type="date"
          value={date}
          max={shiftIsoDate(today, 1)}
          onChange={(e) => e.target.value && onChange(e.target.value)}
          aria-label={`Elegir otro día (mostrando ${relativeDayLabel(date, today)})`}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
      </div>
      <button
        type="button"
        onClick={() => onChange(shiftIsoDate(date, 1))}
        disabled={date >= shiftIsoDate(today, 1)}
        aria-label="Día siguiente"
        className={round}
      >
        <ChevronRight size={20} aria-hidden="true" />
      </button>
      {date !== today && (
        <button
          type="button"
          onClick={() => onChange(today)}
          className="min-h-10 rounded-full bg-[var(--color-primary-soft)] px-4 text-sm font-bold text-[var(--color-primary)]"
        >
          Ir a hoy
        </button>
      )}
    </div>
  );
}
