"use client";

import { Scale, TrendingDown, TrendingUp } from "lucide-react";
import { useId, useState } from "react";
import { useContainerWidth } from "@/components/ui/useContainerWidth";
import {
  axisDates,
  formatKg,
  niceTicks,
  normalizePoints,
  shortDate,
  signedKg,
  totalChangeKg,
  trendKgPerWeek,
  withMovingAverage,
  type WeightPoint,
} from "@/lib/weightTrend";

const PAD = { left: 46, right: 16, top: 18, bottom: 34 };
/** Alto de la gráfica. Más bajo en pantalla estrecha: en un móvil, 300 px de alto empujan
 * todo lo demás fuera de la pantalla. */
const height = (width: number) => (width < 520 ? 210 : 300);

const DAY_MS = 24 * 60 * 60 * 1000;
const time = (date: string) => new Date(`${date}T00:00:00`).getTime();

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[var(--radius-card)] bg-[var(--color-surface-2)] px-3 py-2.5">
      <p className="text-xs text-[var(--color-muted)]">{label}</p>
      <p className="text-lg font-extrabold tracking-tight">{value}</p>
      {hint && <p className="text-[11px] text-[var(--color-muted)]">{hint}</p>}
    </div>
  );
}

/** Panel de tendencia de peso: la media móvil como línea con área, cada pesada como punto,
 * cuadrícula con kilos legibles y fechas repartidas por el eje.
 *
 * Deliberadamente sin colores de «bien» y «mal» (R10): subir o bajar se dibuja igual, y el
 * resumen dice cuánto ha cambiado sin calificarlo. Lo que sí se destaca es la media de 7
 * días, porque la báscula oscila casi un kilo de un día para otro y sin suavizar no se ve
 * nada. */
export function WeightTrend({
  points,
  caption,
}: {
  points: WeightPoint[];
  caption?: string;
}) {
  const gradientId = useId();
  const [hover, setHover] = useState<number | null>(null);
  // El SVG se dibuja al tamaño real del hueco (no escalado): así las etiquetas de los ejes
  // se leen igual en un móvil que en un escritorio.
  const { ref, width: boxWidth } = useContainerWidth();
  const VIEW = { width: Math.max(280, boxWidth), height: height(boxWidth) };
  const INNER_W = VIEW.width - PAD.left - PAD.right;
  const INNER_H = VIEW.height - PAD.top - PAD.bottom;

  const series = withMovingAverage(normalizePoints(points));
  if (series.length === 0) {
    return (
      <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-border-strong)] p-6 text-center">
        <Scale size={22} aria-hidden="true" className="mx-auto mb-2 text-[var(--color-muted)]" />
        <p className="text-sm font-semibold">Todavía no hay pesadas</p>
        <p className="mt-1 text-xs text-[var(--color-muted)]">
          Guarda una medida y aquí verás tu tendencia, suavizada para que el vaivén de un día
          para otro no despiste.
        </p>
      </div>
    );
  }

  const values = series.flatMap((d) => [d.weightKg, d.averageKg ?? d.weightKg]);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const yMin = ticks[0] ?? Math.min(...values);
  const yMax = ticks[ticks.length - 1] ?? Math.max(...values);
  const range = yMax - yMin || 1;

  const t0 = time(series[0].date);
  const span = time(series[series.length - 1].date) - t0;
  const x = (date: string) =>
    span === 0 ? PAD.left + INNER_W / 2 : PAD.left + ((time(date) - t0) / span) * INNER_W;
  const y = (value: number) => PAD.top + (1 - (value - yMin) / range) * INNER_H;

  const averages = series.filter((d) => d.averageKg != null);
  const line = averages
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(d.date)},${y(d.averageKg as number)}`)
    .join(" ");
  const area =
    averages.length > 1
      ? `${line} L${x(averages[averages.length - 1].date)},${y(yMin)} L${x(averages[0].date)},${y(yMin)} Z`
      : "";

  const change = totalChangeKg(series);
  const trend = trendKgPerWeek(series);
  const last = series[series.length - 1];
  const labels = axisDates(series);
  const days = Math.round((time(last.date) - t0) / DAY_MS) + 1;
  const active = hover != null ? series[hover] : null;
  const TrendIcon = trend != null && trend < 0 ? TrendingDown : TrendingUp;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Figure
          label="Último peso"
          value={`${formatKg(last.weightKg)} kg`}
          hint={shortDate(last.date)}
        />
        <Figure
          label="Cambio total"
          value={change != null ? `${signedKg(change)} kg` : "—"}
          hint={change != null ? `en ${days} días` : "hacen falta dos pesadas"}
        />
        <Figure
          label="Ritmo"
          value={trend != null ? `${signedKg(trend, 2)} kg/sem` : "—"}
          hint={trend != null ? "según todas tus pesadas" : "hacen falta dos días distintos"}
        />
        <Figure label="Pesadas" value={String(series.length)} hint="registradas" />
      </div>

      <div className="relative" ref={ref}>
        <svg
          viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
          width="100%"
          height={VIEW.height}
          className="w-full touch-pan-y"
          role="img"
          aria-label={`Peso de ${shortDate(series[0].date)} a ${shortDate(last.date)}: de ${formatKg(
            series[0].weightKg,
          )} a ${formatKg(last.weightKg)} kilos${
            trend != null ? `, con una tendencia de ${signedKg(trend, 2)} kilos por semana` : ""
          }`}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-primary)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--color-primary)" stopOpacity={0} />
            </linearGradient>
          </defs>

          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={VIEW.width - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="currentColor"
                strokeWidth={1}
                opacity={0.12}
              />
              <text
                x={PAD.left - 8}
                y={y(tick) + 4}
                fontSize="12"
                textAnchor="end"
                fill="currentColor"
                opacity={0.55}
              >
                {formatKg(tick, tick % 1 === 0 ? 0 : 1)}
              </text>
            </g>
          ))}

          {area && <path d={area} fill={`url(#${gradientId})`} />}
          {averages.length > 1 && (
            <path
              d={line}
              fill="none"
              stroke="var(--color-primary)"
              strokeWidth={3}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {series.map((d, i) => (
            <circle
              key={d.date}
              cx={x(d.date)}
              cy={y(d.weightKg)}
              r={hover === i ? 6 : 3.5}
              fill="var(--color-surface)"
              stroke="var(--color-primary)"
              strokeWidth={2}
            />
          ))}

          {/* Franjas invisibles: dan un objetivo ancho al dedo y al ratón, que un punto de
              3 px no da. */}
          {series.map((d, i) => (
            <rect
              key={`hit-${d.date}`}
              x={x(d.date) - INNER_W / (2 * Math.max(1, series.length - 1)) - 6}
              y={PAD.top}
              width={INNER_W / Math.max(1, series.length - 1) + 12}
              height={INNER_H}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onTouchStart={() => setHover(i)}
            />
          ))}

          {active && (
            <line
              x1={x(active.date)}
              x2={x(active.date)}
              y1={PAD.top}
              y2={PAD.top + INNER_H}
              stroke="var(--color-primary)"
              strokeWidth={1}
              strokeDasharray="4 4"
              opacity={0.5}
            />
          )}

          {labels.map((date) => (
            <text
              key={date}
              x={x(date)}
              y={VIEW.height - 10}
              fontSize="12"
              textAnchor="middle"
              fill="currentColor"
              opacity={0.55}
            >
              {shortDate(date)}
            </text>
          ))}
        </svg>

        {active && (
          <p
            role="status"
            className="pointer-events-none absolute right-2 top-0 rounded-full bg-[var(--color-primary)] px-3 py-1 text-xs font-bold text-[var(--color-on-primary)] shadow-md"
          >
            {shortDate(active.date)} · {formatKg(active.weightKg)} kg
            {active.averageKg != null && ` · media ${formatKg(active.averageKg)}`}
          </p>
        )}
      </div>

      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-muted)]">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-5 rounded-full bg-[var(--color-primary)]" />
          Media de 7 días
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-[var(--color-primary)] bg-[var(--color-surface)]" />
          Cada pesada
        </span>
        {trend != null && (
          <span className="flex items-center gap-1.5">
            <TrendIcon size={13} aria-hidden="true" />
            {signedKg(trend, 2)} kg por semana
          </span>
        )}
      </p>
      <p className="text-xs text-[var(--color-muted)]">
        {caption ??
          "La línea es la media de los últimos 7 días: el peso de un día suelto sube y baja " +
            "por agua y digestión, así que la tendencia dice más que cualquier pesada."}
      </p>
    </div>
  );
}
