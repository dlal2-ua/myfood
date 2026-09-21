import { calorieBudget } from "@/lib/today";

/** Anillo grande de calorías del día. En el centro, lo que queda hasta el objetivo. Pasarse no
 * cambia el color (R10): el texto dice cuántas kcal se han superado. */
export function BudgetRing({
  consumed,
  target,
  className = "h-36 w-36",
}: {
  consumed: number;
  target: number | null | undefined;
  /** Tamaño con clases de Tailwind (el dibujo se escala). */
  className?: string;
}) {
  const size = 148;
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const budget = calorieBudget(consumed, target);
  const eaten = Math.round(consumed);

  const description = budget
    ? `Calorías: ${eaten} de ${Math.round(target ?? 0)} kcal. ${
        budget.over > 0 ? `${budget.over} kcal por encima del objetivo` : `Quedan ${budget.remaining} kcal`
      }`
    : `Calorías: ${eaten} kcal`;

  return (
    <div role="group" aria-label={description} className={`relative shrink-0 ${className}`}>
      <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-surface-2)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - (budget?.fraction ?? 0))}
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center leading-tight" aria-hidden="true">
        {budget ? (
          <>
            <span className="text-2xl font-extrabold tracking-tight sm:text-3xl">
              {budget.over > 0 ? `+${budget.over}` : budget.remaining}
            </span>
            <span className="text-xs font-medium text-[var(--color-muted)]">
              {budget.over > 0 ? "sobre el objetivo" : "restantes"}
            </span>
          </>
        ) : (
          <>
            <span className="text-2xl font-extrabold tracking-tight sm:text-3xl">{eaten}</span>
            <span className="text-xs font-medium text-[var(--color-muted)]">kcal</span>
          </>
        )}
      </div>
    </div>
  );
}
