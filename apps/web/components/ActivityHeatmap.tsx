"use client";

import { useState } from "react";
import {
  WEEKDAY_INITIALS,
  buildWeeks,
  describeDay,
  intensityLevel,
  monthLabels,
  type HeatmapDay,
} from "@/lib/heatmap";

const CELL = 12;
const GAP = 3;
const STEP = CELL + GAP;
const LABEL_W = 16;
const MONTH_H = 16;

/** Verde neutro por intensidad de registro — nunca rojo, nunca ligado a si se cumplió el
 * objetivo calórico (R10). Colorea «hubo actividad», no «resultado». */
const LEVEL_COLOR = [
  "color-mix(in srgb, currentColor 10%, transparent)",
  "color-mix(in srgb, var(--color-primary) 28%, transparent)",
  "color-mix(in srgb, var(--color-primary) 62%, transparent)",
  "var(--color-primary)",
];

/** Último año de registro, una columna por semana. Las etiquetas de mes van arriba y las
 * iniciales de los días a la izquierda: sin ellas, 52 columnas de cuadraditos no dicen en
 * qué época del año cae cada racha. */
export function ActivityHeatmap({ days }: { days: HeatmapDay[] }) {
  const [active, setActive] = useState<HeatmapDay | null>(null);
  const weeks = buildWeeks(days);
  const months = monthLabels(weeks);
  const width = LABEL_W + weeks.length * STEP;
  const height = MONTH_H + 7 * STEP;
  const registered = days.filter((d) => d.count > 0).length;

  if (weeks.length === 0) {
    return <p className="text-sm text-[var(--color-muted)]">Todavía no hay nada que enseñar aquí.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="scroll-row -mx-4 overflow-x-auto px-4 md:mx-0 md:px-0">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          role="img"
          aria-label={`Actividad del último año: ${registered} días con registro de ${days.length}.`}
          className="max-w-none"
          onMouseLeave={() => setActive(null)}
        >
          {months.map((month) => (
            <text
              key={`${month.label}-${month.weekIndex}`}
              x={LABEL_W + month.weekIndex * STEP}
              y={11}
              fontSize="10"
              fill="currentColor"
              opacity={0.6}
            >
              {month.label}
            </text>
          ))}

          {/* Lunes, miércoles y viernes: con los siete la columna se apelmaza. */}
          {[0, 2, 4].map((row) => (
            <text
              key={row}
              x={0}
              y={MONTH_H + row * STEP + CELL - 2}
              fontSize="9"
              fill="currentColor"
              opacity={0.5}
            >
              {WEEKDAY_INITIALS[row]}
            </text>
          ))}

          {weeks.map((week, wi) =>
            week.map((day, di) =>
              day ? (
                <rect
                  key={day.date}
                  x={LABEL_W + wi * STEP}
                  y={MONTH_H + di * STEP}
                  width={CELL}
                  height={CELL}
                  rx={2.5}
                  fill={LEVEL_COLOR[intensityLevel(day.count)]}
                  onMouseEnter={() => setActive(day)}
                  onTouchStart={() => setActive(day)}
                >
                  <title>{describeDay(day)}</title>
                </rect>
              ) : null,
            ),
          )}
        </svg>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--color-muted)]">
        <span role="status" aria-live="polite">
          {active ? describeDay(active) : `${registered} días con registro en el último año`}
        </span>
        <span className="flex items-center gap-1.5">
          Menos
          {LEVEL_COLOR.map((color) => (
            <span
              key={color}
              aria-hidden="true"
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: color }}
            />
          ))}
          Más
        </span>
      </div>
    </div>
  );
}
