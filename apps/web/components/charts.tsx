"use client";

import { useContainerWidth } from "@/components/ui/useContainerWidth";
import { shortDate } from "@/lib/weightTrend";

/** Minimal hand-rolled SVG charts — no charting library needed for a
 * "frontend mínimo": a few bars / a polyline are plenty. */

export interface BarDatum {
  label: string;
  value: number;
  color: string;
}

export function BarChart({ data, unit = "" }: { data: BarDatum[]; unit?: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const width = 320;
  const barHeight = 28;
  const gap = 10;
  const labelWidth = 70;
  const chartWidth = width - labelWidth;
  const height = data.length * (barHeight + gap);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="Reparto de macronutrientes">
      {data.map((d, i) => {
        const barWidth = Math.max(2, (d.value / max) * chartWidth);
        const y = i * (barHeight + gap);
        return (
          <g key={d.label}>
            <text x={0} y={y + barHeight / 2 + 4} fontSize="11" fill="currentColor">
              {d.label}
            </text>
            <rect
              x={labelWidth}
              y={y}
              width={chartWidth}
              height={barHeight}
              rx={4}
              fill="currentColor"
              opacity={0.08}
            />
            <rect x={labelWidth} y={y} width={barWidth} height={barHeight} rx={4} fill={d.color} />
            <text
              x={labelWidth + barWidth + 6}
              y={y + barHeight / 2 + 4}
              fontSize="11"
              fill="currentColor"
            >
              {d.value}
              {unit}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export interface DailyBarDatum {
  date: string;
  value: number;
}

/** Barras por día con una línea de referencia (p. ej. el objetivo calórico). La barra es
 * siempre del mismo color: pasarse o quedarse corto no se marca como bueno o malo (R10).
 *
 * Se dibuja al ancho real del hueco, no con un `viewBox` fijo escalado: escalado, en un móvil
 * las fechas de los ejes acababan en letra minúscula y en escritorio desproporcionadas. */
export function DailyBarsChart({
  data,
  reference,
  unit = "",
  referenceLabel = "Tu objetivo",
}: {
  data: DailyBarDatum[];
  reference?: number | null;
  unit?: string;
  referenceLabel?: string;
}) {
  const { ref, width: boxWidth } = useContainerWidth();
  if (data.length === 0) {
    return (
      <p className="text-sm text-[var(--color-muted)]">Aún no hay registros en este periodo.</p>
    );
  }
  const width = Math.max(280, boxWidth);
  const height = width < 520 ? 170 : 220;
  const pad = { left: 46, right: 14, top: 14, bottom: 28 };
  const max = Math.max(...data.map((d) => d.value), reference ?? 0, 1) * 1.1;
  const innerWidth = width - pad.left - pad.right;
  const slot = innerWidth / data.length;
  const barWidth = Math.max(2, Math.min(18, slot - 2));
  const y = (v: number) => pad.top + (1 - v / max) * (height - pad.top - pad.bottom);
  const x = (i: number) => pad.left + (i + 0.5) * slot;
  const ticks = [0, max / 2, max].map((v) => Math.round(v / 50) * 50);

  return (
    <div ref={ref} className="flex flex-col gap-1.5">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        className="w-full"
        role="img"
        aria-label={`Consumo diario de ${shortDate(data[0].date)} a ${shortDate(
          data[data.length - 1].date,
        )}${reference ? `, con tu objetivo de ${Math.round(reference)}${unit}` : ""}`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="currentColor"
              opacity={0.12}
            />
            <text
              x={pad.left - 8}
              y={y(tick) + 4}
              fontSize="12"
              textAnchor="end"
              fill="currentColor"
              opacity={0.55}
            >
              {tick}
            </text>
          </g>
        ))}

        {data.map((d, i) => (
          <rect
            key={d.date}
            x={x(i) - barWidth / 2}
            y={y(d.value)}
            width={barWidth}
            height={Math.max(1, y(0) - y(d.value))}
            rx={3}
            fill="var(--color-primary)"
            opacity={0.8}
          >
            <title>{`${shortDate(d.date)}: ${Math.round(d.value)}${unit}`}</title>
          </rect>
        ))}

        {reference != null && (
          <line
            x1={pad.left}
            x2={width - pad.right}
            y1={y(reference)}
            y2={y(reference)}
            stroke="var(--color-accent, var(--color-primary))"
            strokeWidth={2}
            strokeDasharray="6 4"
          />
        )}

        {[0, Math.floor((data.length - 1) / 2), data.length - 1]
          .filter((i, idx, all) => all.indexOf(i) === idx)
          .map((i) => (
            <text
              key={data[i].date}
              x={x(i)}
              y={height - 8}
              fontSize="12"
              textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}
              fill="currentColor"
              opacity={0.55}
            >
              {shortDate(data[i].date)}
            </text>
          ))}
      </svg>
      {reference != null && (
        <p className="flex items-center gap-1.5 text-xs text-[var(--color-muted)]">
          <span
            aria-hidden="true"
            className="inline-block h-0 w-5 border-t-2 border-dashed border-[var(--color-accent,var(--color-primary))]"
          />
          {referenceLabel}: {Math.round(reference)}
          {unit}
        </p>
      )}
    </div>
  );
}
