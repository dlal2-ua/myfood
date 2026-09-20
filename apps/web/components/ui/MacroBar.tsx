export interface MacroSlice {
  key: string;
  label: string;
  grams: number;
  color: string;
}

/** Reparto de macros en una barra apilada. Cada tramo lleva su etiqueta de texto y sus gramos:
 * el color por sí solo nunca da la información. */
export function MacroBar({ slices }: { slices: MacroSlice[] }) {
  const total = slices.reduce((sum, s) => sum + Math.max(0, s.grams), 0);
  if (total <= 0) {
    return <p className="text-xs text-neutral-500">Todavía no hay macros que repartir.</p>;
  }
  return (
    <div>
      <div
        role="img"
        aria-label={slices
          .map((s) => `${s.label} ${Math.round((100 * s.grams) / total)} %`)
          .join(", ")}
        className="flex h-3 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800"
      >
        {slices.map((s) => (
          <div
            key={s.key}
            style={{ width: `${(100 * Math.max(0, s.grams)) / total}%`, backgroundColor: s.color }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {slices.map((s) => (
          <li key={s.key} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: s.color }}
              aria-hidden="true"
            />
            {s.label}: {Math.round(s.grams)} g
          </li>
        ))}
      </ul>
    </div>
  );
}
