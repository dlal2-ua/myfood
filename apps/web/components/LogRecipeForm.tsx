"use client";

import { useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import { mealTypeForTime } from "@/lib/meals";
import { MEAL_TYPES, MEAL_TYPE_LABELS } from "@/lib/types";
import type { MealType, Recipe } from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

/** Registra raciones de una receta propia en el día (`POST /api/log/recipe`) y ofrece la etiqueta
 * imprimible con su código de barras interno. */
export function LogRecipeForm({ recipe }: { recipe: Recipe }) {
  const [servings, setServings] = useState("1");
  const [mealType, setMealType] = useState<MealType>(() => mealTypeForTime());
  const [date, setDate] = useState(() => localDateIso());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onLog(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await apiFetch("/api/log/recipe", {
        method: "POST",
        body: JSON.stringify({
          log_date: date,
          meal_type: mealType,
          recipe_id: recipe.id,
          servings: Number(servings),
        }),
      });
      setMessage(`Registrado en ${MEAL_TYPE_LABELS[mealType].toLowerCase()} del ${date}.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 flex flex-col gap-3 border-t border-neutral-200 pt-4 dark:border-neutral-800">
      <form onSubmit={onLog} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Raciones
          <input
            type="number"
            min={0.25}
            max={20}
            step={0.25}
            required
            className={`${inputClass} w-24`}
            value={servings}
            onChange={(e) => setServings(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Comida
          <select
            className={inputClass}
            value={mealType}
            onChange={(e) => setMealType(e.target.value as MealType)}
          >
            {MEAL_TYPES.map((m) => (
              <option key={m} value={m}>
                {MEAL_TYPE_LABELS[m]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Fecha
          <input
            type="date"
            required
            className={inputClass}
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
        >
          {busy ? "Registrando…" : "Registrar"}
        </button>
      </form>
      {message && <p className="text-sm text-[var(--color-primary)]">{message}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {recipe.internal_ean && (
        <p className="text-xs text-neutral-500">
          Código de la receta: {recipe.internal_ean}.{" "}
          <a
            href={`/api/recipes/${recipe.id}/label.svg`}
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            Imprimir etiqueta
          </a>{" "}
          para pegarla en el táper y registrarla luego con el escáner.
        </p>
      )}
    </div>
  );
}
