/** Progreso circular de un valor frente a su objetivo. No juzga: pasarse o quedarse corto no cambia
 * el color (R10); el texto siempre dice el número, nunca solo el color. */
export function Ring({
  value,
  target,
  color,
  label,
  unit,
  size = 96,
}: {
  value: number;
  target: number | null | undefined;
  color: string;
  label: string;
  unit: string;
  size?: number;
}) {
  const stroke = 9;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const fraction = target && target > 0 ? Math.min(1, Math.max(0, value / target)) : 0;
  const rounded = Math.round(value);
  const description = target
    ? `${label}: ${rounded} de ${Math.round(target)} ${unit}`
    : `${label}: ${rounded} ${unit}`;

  return (
    <div className="flex flex-col items-center gap-1 text-center" role="group" aria-label={description}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} className="-rotate-90" aria-hidden="true">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            opacity={0.12}
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - fraction)}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center leading-tight">
          <span className="text-lg font-semibold">{rounded}</span>
          {target ? (
            <span className="text-[10px] text-neutral-500">/ {Math.round(target)}</span>
          ) : null}
        </div>
      </div>
      <span className="text-xs font-medium">{label}</span>
      <span className="text-[10px] text-neutral-500">{unit}</span>
    </div>
  );
}
