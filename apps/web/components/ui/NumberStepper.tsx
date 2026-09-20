"use client";

/** Cantidad con botones − y + de al menos 44 px (para gramos, raciones…). */
export function NumberStepper({
  value,
  onChange,
  label,
  min = 0,
  max = 5000,
  step = 5,
  unit = "g",
}: {
  value: number;
  onChange: (next: number) => void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
}) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n));
  const button =
    "flex h-11 w-11 items-center justify-center rounded-[var(--radius-control)] border border-neutral-300 text-lg disabled:opacity-40 dark:border-neutral-700";
  return (
    <div role="group" aria-label={label} className="inline-flex items-center gap-1">
      <button
        type="button"
        className={button}
        aria-label={`Quitar ${step} ${unit}`}
        disabled={value <= min}
        onClick={() => onChange(clamp(value - step))}
      >
        −
      </button>
      <label className="flex items-center gap-1">
        <span className="sr-only">{label}</span>
        <input
          type="number"
          inputMode="decimal"
          value={Number.isFinite(value) ? value : ""}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(clamp(Number(e.target.value)))}
          className="h-11 w-20 rounded-[var(--radius-control)] border border-neutral-300 px-2 text-center dark:border-neutral-700 dark:bg-neutral-900"
        />
        <span className="text-sm text-neutral-500">{unit}</span>
      </label>
      <button
        type="button"
        className={button}
        aria-label={`Añadir ${step} ${unit}`}
        disabled={value >= max}
        onClick={() => onChange(clamp(value + step))}
      >
        +
      </button>
    </div>
  );
}
