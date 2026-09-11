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
