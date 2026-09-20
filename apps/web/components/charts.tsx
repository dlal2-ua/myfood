"use client";

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

export interface PointDatum {
  label: string;
  value: number;
}

export function LineChart({ data, unit = "" }: { data: PointDatum[]; unit?: string }) {
  const width = 320;
  const height = 140;
  const padding = 28;

  if (data.length === 0) {
    return <p className="text-sm text-neutral-500">Sin datos todavía.</p>;
  }

  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const innerWidth = width - padding * 2;
  const innerHeight = height - padding * 2;

  const points = data.map((d, i) => {
    const x = padding + (data.length === 1 ? innerWidth / 2 : (i / (data.length - 1)) * innerWidth);
    const y = padding + innerHeight - ((d.value - min) / range) * innerHeight;
    return { x, y, ...d };
  });

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="Tendencia de peso">
      <path d={path} fill="none" stroke="var(--color-primary)" strokeWidth={2} />
      {points.map((p) => (
        <g key={p.label}>
          <circle cx={p.x} cy={p.y} r={3} fill="var(--color-primary)" />
        </g>
      ))}
      <text x={points[0].x} y={height - 4} fontSize="10" fill="currentColor" textAnchor="start">
        {points[0].label}
      </text>
      <text
        x={points[points.length - 1].x}
        y={height - 4}
        fontSize="10"
        fill="currentColor"
        textAnchor="end"
      >
        {points[points.length - 1].label}
      </text>
      <text x={padding} y={12} fontSize="10" fill="currentColor">
        {max.toFixed(1)}
        {unit}
      </text>
      <text x={padding} y={height - padding + 14} fontSize="10" fill="currentColor">
        {min.toFixed(1)}
        {unit}
      </text>
    </svg>
  );
}

export interface WeightPointDatum {
  date: string;
  weight: number;
  average: number;
}

/** Peso diario (puntos) y su media móvil de 7 días (línea). Sin escala de colores que juzgue
 * subidas o bajadas (R10): son los números del usuario, no un veredicto. */
export function WeightTrendChart({ data }: { data: WeightPointDatum[] }) {
  const width = 340;
  const height = 170;
  const pad = { left: 38, right: 10, top: 12, bottom: 24 };
  if (data.length === 0) {
    return <p className="text-sm text-neutral-500">Aún no hay pesadas en este periodo.</p>;
  }
  const values = data.flatMap((d) => [d.weight, d.average]);
  const min = Math.floor(Math.min(...values) - 0.5);
  const max = Math.ceil(Math.max(...values) + 0.5);
  const range = max - min || 1;
  const t0 = new Date(data[0].date).getTime();
  const t1 = new Date(data[data.length - 1].date).getTime();
  const span = t1 - t0 || 1;
  const x = (date: string) =>
    data.length === 1
      ? (pad.left + width - pad.right) / 2
      : pad.left + ((new Date(date).getTime() - t0) / span) * (width - pad.left - pad.right);
  const y = (v: number) => pad.top + (1 - (v - min) / range) * (height - pad.top - pad.bottom);
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(d.date)},${y(d.average)}`).join(" ");

  return (
    <>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        role="img"
        aria-label={`Peso de ${data[0].date} a ${data[data.length - 1].date}: de ${data[0].weight} kg a ${data[data.length - 1].weight} kg, con su media móvil de 7 días`}
      >
        {[min, (min + max) / 2, max].map((tick) => (
          <g key={tick}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="currentColor"
              opacity={0.12}
            />
            <text x={pad.left - 4} y={y(tick) + 3} fontSize="10" textAnchor="end" fill="currentColor">
              {tick % 1 === 0 ? tick : tick.toFixed(1)}
            </text>
          </g>
        ))}
        {data.map((d) => (
          <circle key={d.date} cx={x(d.date)} cy={y(d.weight)} r={2.5} fill="currentColor" opacity={0.45}>
            <title>{`${d.date}: ${d.weight} kg`}</title>
          </circle>
        ))}
        {data.length > 1 && (
          <path d={line} fill="none" stroke="var(--color-primary)" strokeWidth={2.5} />
        )}
        <text x={pad.left} y={height - 6} fontSize="10" fill="currentColor">
          {data[0].date.slice(5)}
        </text>
        <text x={width - pad.right} y={height - 6} fontSize="10" textAnchor="end" fill="currentColor">
          {data[data.length - 1].date.slice(5)}
        </text>
      </svg>
      <p className="mt-1 flex items-center gap-3 text-xs text-neutral-500">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-full bg-current opacity-45" /> Peso
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 bg-[var(--color-primary)]" /> Media de 7 días
        </span>
      </p>
    </>
  );
}

export interface DailyBarDatum {
  date: string;
  value: number;
}

/** Barras por día con una línea de referencia (p. ej. el objetivo calórico). La barra es
 * siempre del mismo color: pasarse o quedarse corto no se marca como bueno o malo (R10). */
export function DailyBarsChart({
  data,
  reference,
  unit = "",
}: {
  data: DailyBarDatum[];
  reference?: number | null;
  unit?: string;
}) {
  const width = 340;
  const height = 150;
  const pad = { left: 38, right: 10, top: 10, bottom: 22 };
  if (data.length === 0) {
    return <p className="text-sm text-neutral-500">Aún no hay registros en este periodo.</p>;
  }
  const max = Math.max(...data.map((d) => d.value), reference ?? 0, 1) * 1.1;
  const innerWidth = width - pad.left - pad.right;
  const barWidth = Math.max(2, Math.min(14, innerWidth / data.length - 2));
  const y = (v: number) => pad.top + (1 - v / max) * (height - pad.top - pad.bottom);
  const x = (i: number) => pad.left + ((i + 0.5) / data.length) * innerWidth;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      role="img"
      aria-label={`Consumo diario de ${data[0].date} a ${data[data.length - 1].date}${
        reference ? `, con tu objetivo de ${reference}${unit}` : ""
      }`}
    >
      <line x1={pad.left} x2={width - pad.right} y1={y(0)} y2={y(0)} stroke="currentColor" opacity={0.2} />
      {data.map((d, i) => (
        <rect
          key={d.date}
          x={x(i) - barWidth / 2}
          y={y(d.value)}
          width={barWidth}
          height={Math.max(1, y(0) - y(d.value))}
          rx={1.5}
          fill="var(--color-primary)"
          opacity={0.75}
        >
          <title>{`${d.date}: ${Math.round(d.value)}${unit}`}</title>
        </rect>
      ))}
      {reference != null && (
        <g>
          <line
            x1={pad.left}
            x2={width - pad.right}
            y1={y(reference)}
            y2={y(reference)}
            stroke="currentColor"
            strokeDasharray="4 3"
            opacity={0.6}
          />
          <text x={pad.left - 4} y={y(reference) + 3} fontSize="10" textAnchor="end" fill="currentColor">
            {Math.round(reference)}
          </text>
        </g>
      )}
      <text x={pad.left} y={height - 6} fontSize="10" fill="currentColor">
        {data[0].date.slice(5)}
      </text>
      <text x={width - pad.right} y={height - 6} fontSize="10" textAnchor="end" fill="currentColor">
        {data[data.length - 1].date.slice(5)}
      </text>
    </svg>
  );
}
