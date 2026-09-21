"use client";

import { BottomSheet } from "@/components/ui/BottomSheet";
import { FACET_HINTS, FACET_TITLES, visibleOptions, type FacetKey } from "@/lib/foodFilters";
import type { FacetOption } from "@/lib/types";

/** Hoja con las opciones de un filtro (supermercado, tipo de alimento o nutrición). Cada opción
 * enseña cuántos alimentos dejaría; los resultados de detrás se actualizan al marcar. */
export function FacetSheet({
  facetKey,
  options,
  selected,
  total,
  loading,
  onToggle,
  onClear,
  onClose,
}: {
  facetKey: FacetKey | null;
  options: FacetOption[];
  selected: string[];
  /** `null` mientras no hay nada elegido con lo que buscar. */
  total: number | null;
  loading: boolean;
  onToggle: (code: string) => void;
  onClear: () => void;
  onClose: () => void;
}) {
  if (!facetKey) return null;
  const shown = visibleOptions(facetKey, options, selected);
  return (
    <BottomSheet open onClose={onClose} title={FACET_TITLES[facetKey]}>
      <p className="-mt-2 mb-3 text-sm text-[var(--color-muted)]">{FACET_HINTS[facetKey]}</p>
      {shown.length === 0 ? (
        <p className="rounded-2xl bg-[var(--color-surface-2)] p-4 text-sm text-[var(--color-muted)]">
          Con lo que ya has elegido no queda ninguna opción más.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {shown.map((option) => {
            const checked = selected.includes(option.code);
            const unavailable = option.count === 0 && !checked;
            return (
              <li key={option.code}>
                <label
                  className={`flex min-h-12 cursor-pointer items-center gap-3 rounded-2xl px-3 py-1.5 transition-colors hover:bg-[var(--color-surface-2)] ${
                    unavailable ? "opacity-50" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggle(option.code)}
                    className="h-5 w-5 shrink-0"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-semibold">{option.label}</span>
                    {option.description && (
                      <span className="block text-xs leading-snug text-[var(--color-muted)]">{option.description}</span>
                    )}
                  </span>
                  <span className="shrink-0 rounded-full bg-[var(--color-surface-2)] px-2 py-0.5 text-xs font-semibold text-[var(--color-muted)]">
                    {option.count}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <div className="mt-4 flex gap-3">
        <button
          type="button"
          onClick={onClear}
          disabled={selected.length === 0}
          className="min-h-12 flex-1 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold disabled:opacity-40"
        >
          Quitar
        </button>
        <button
          type="button"
          onClick={onClose}
          className="min-h-12 flex-[2] rounded-full bg-[var(--color-primary)] text-sm font-bold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)]"
        >
          {total === null ? "Listo" : loading ? "Buscando…" : `Ver ${total} ${total === 1 ? "alimento" : "alimentos"}`}
        </button>
      </div>
    </BottomSheet>
  );
}
