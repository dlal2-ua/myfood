"use client";

import { Minus, Plus } from "lucide-react";
import {
  GRAMS_KEY,
  describeAmount,
  formatNumber,
  macrosFor,
  toQuantity,
  type Per100g,
  type Portion,
} from "@/lib/portions";

const STEP_BY_KEY = (portion: Portion) => (portion.key === GRAMS_KEY ? 10 : 0.5);

/** Cantidad + medida casera, con los gramos resultantes siempre a la vista.
 *
 * Antes solo se podían escribir gramos, y para apuntar dos huevos había que saber de memoria
 * lo que pesa un huevo. Los gramos de cada medida vienen del servidor (R1). */
export function PortionPicker({
  portions,
  portion,
  quantity,
  onChange,
  disabled,
}: {
  portions: Portion[];
  portion: Portion;
  quantity: number;
  onChange: (next: { portion: Portion; quantity: number }) => void;
  disabled?: boolean;
}) {
  const step = STEP_BY_KEY(portion);
  const bump = (delta: number) =>
    onChange({ portion, quantity: Math.max(step, Math.round((quantity + delta) * 100) / 100) });

  function changePortion(key: string) {
    const next = portions.find((p) => p.key === key);
    if (!next) return;
    // Se conserva lo que pesa, no el número: pasar de «2 huevos» a gramos debe dar 120 g,
    // no 2 g.
    const grams = quantity * portion.grams;
    onChange({ portion: next, quantity: toQuantity(grams, next) });
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex flex-col gap-1">
        <label htmlFor="portion-quantity" className="text-xs font-semibold text-[var(--color-muted)]">
          Cantidad
        </label>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => bump(-step)}
            disabled={disabled || quantity <= step}
            aria-label="Quitar"
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[var(--color-border-strong)] disabled:opacity-40"
          >
            <Minus size={16} aria-hidden="true" />
          </button>
          <input
            id="portion-quantity"
            type="number"
            inputMode="decimal"
            min={0}
            step={step}
            value={quantity}
            disabled={disabled}
            onChange={(e) => onChange({ portion, quantity: Number(e.target.value) })}
            className="h-11 w-20 rounded-[var(--radius-control)] text-center text-base font-bold"
          />
          <button
            type="button"
            onClick={() => bump(step)}
            disabled={disabled}
            aria-label="Añadir"
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[var(--color-border-strong)] disabled:opacity-40"
          >
            <Plus size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <label className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-xs font-semibold text-[var(--color-muted)]">Medida</span>
        <select
          value={portion.key}
          disabled={disabled}
          onChange={(e) => changePortion(e.target.value)}
          className="h-11 w-full rounded-[var(--radius-control)] px-3 text-sm font-semibold"
        >
          {portions.map((p) => (
            <option key={p.key} value={p.key}>
              {p.key === GRAMS_KEY ? "gramos" : `${p.label} (${formatNumber(p.grams)} g)`}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/** Lo que va a sumar al día, calculado en el momento. Es la misma cuenta que hace el servidor
 * al guardar (valor por 100 g × gramos ÷ 100): aquí solo sirve para verlo antes de confirmar. */
export function MacroPreview({
  per100g,
  grams,
  quantity,
  portion,
}: {
  per100g: Per100g;
  grams: number;
  quantity: number;
  portion: Portion;
}) {
  const macros = macrosFor(per100g, grams);
  const cells = [
    { label: "Proteína", value: macros.protein, color: "var(--color-protein)" },
    { label: "Carbos", value: macros.carbs, color: "var(--color-carbs)" },
    { label: "Grasa", value: macros.fat, color: "var(--color-fat)" },
  ];
  return (
    <div className="rounded-[var(--radius-card)] bg-[var(--color-surface-2)] p-3">
      <p className="flex items-baseline justify-between gap-3">
        <span className="text-2xl font-extrabold tracking-tight">{macros.kcal} kcal</span>
        <span className="text-xs text-[var(--color-muted)]">{describeAmount(quantity, portion)}</span>
      </p>
      <ul className="mt-2 grid grid-cols-3 gap-2 text-center">
        {cells.map((cell) => (
          <li key={cell.label}>
            <span className="flex items-center justify-center gap-1 text-[11px] text-[var(--color-muted)]">
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: cell.color }}
              />
              {cell.label}
            </span>
            <span className="text-sm font-bold">{formatNumber(cell.value)} g</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
