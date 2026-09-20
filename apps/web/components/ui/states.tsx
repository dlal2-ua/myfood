import Link from "next/link";

/** Esqueleto de carga (nunca un spinner a pantalla completa). */
export function Skeleton({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={`flex flex-col gap-2 ${className}`}>
      <span className="sr-only">Cargando…</span>
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="skeleton h-4"
          style={{ width: `${100 - ((i * 17) % 40)}%` }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

/** Estado vacío: dice qué pasa y sugiere qué hacer, nunca una pantalla en blanco. */
export function EmptyState({
  message,
  actionLabel,
  actionHref,
  onAction,
}: {
  message: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}) {
  const button =
    "mt-3 inline-block rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm text-white";
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-neutral-300 p-6 text-center dark:border-neutral-700">
      <p className="text-sm text-neutral-600 dark:text-neutral-400">{message}</p>
      {actionLabel && actionHref && (
        <Link href={actionHref} className={button}>
          {actionLabel}
        </Link>
      )}
      {actionLabel && !actionHref && onAction && (
        <button type="button" onClick={onAction} className={button}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}

/** Estado de error: mensaje en español y botón de reintentar. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="rounded-[var(--radius-card)] border border-red-300 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
    >
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-lg border border-red-400 px-3 py-1.5 text-sm dark:border-red-700"
        >
          Reintentar
        </button>
      )}
    </div>
  );
}
