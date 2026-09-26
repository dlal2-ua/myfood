"use client";

import { BookmarkPlus, Repeat2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import {
  MEAL_TYPES,
  MEAL_TYPE_LABELS,
  type MealType,
  type SavedMeal,
} from "@/lib/types";

/** Comidas guardadas: lo de siempre, a un toque.
 *
 * Lo que hace que alguien siga apuntando al tercer día no es la IA, es meter su desayuno de
 * siempre sin volver a buscar cuatro alimentos. Y es también la salida para los platos
 * compuestos que no están en el catálogo: «bocadillo de sobrasada» no existe como alimento,
 * pero guardado una vez es una sola línea con sus calorías y sus macros.
 */

const card =
  "rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)]";
const input =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

export function SavedMeals({
  logDate,
  mealType,
  onLogged,
  reloadKey,
}: {
  logDate: string;
  mealType: MealType;
  onLogged: () => void;
  /** Cambia cuando se guarda una comida nueva, para refrescar la lista. */
  reloadKey: number;
}) {
  const [meals, setMeals] = useState<SavedMeal[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<Record<string, MealType>>({});

  const load = useCallback(async () => {
    try {
      const res = await apiFetch<{ items: SavedMeal[] }>("/api/saved-meals");
      setMeals(res.items);
    } catch {
      // La lista es un atajo: si falla, el resto de la pantalla sigue sirviendo.
      setMeals([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  async function repeat(meal: SavedMeal) {
    setBusy(meal.id);
    setError(null);
    try {
      await apiFetch(`/api/saved-meals/${meal.id}/log`, {
        method: "POST",
        body: JSON.stringify({
          log_date: logDate,
          // La comida que se eligió aquí; si no, la que se suele apuntar; si no, la del día.
          meal_type: target[meal.id] ?? meal.meal_type ?? mealType,
        }),
      });
      onLogged();
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove(meal: SavedMeal) {
    if (!window.confirm(`¿Borrar «${meal.name}»? Lo que ya apuntaste no se toca.`)) return;
    setBusy(meal.id);
    setError(null);
    try {
      await apiFetch(`/api/saved-meals/${meal.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (meals !== null && meals.length === 0) return null;

  return (
    <section id="guardadas" className={`scroll-mt-20 ${card} p-4`}>
      <h2 className="text-lg font-semibold">Lo de siempre</h2>
      <p className="mb-3 text-sm text-neutral-500">
        Comidas que has guardado. Un toque y se apuntan enteras.
      </p>
      {error && <p className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {meals === null ? (
        <div className="h-16 animate-pulse rounded-[var(--radius-control)] bg-[var(--color-surface-2)]" />
      ) : (
        <ul className="flex flex-col gap-2">
          {meals.map((meal) => (
            <li
              key={meal.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-[var(--color-border-strong)] p-3"
            >
              <div className="min-w-[10rem] flex-1">
                <p className="text-sm font-semibold">{meal.name}</p>
                <p className="text-xs text-neutral-500">
                  {Math.round(meal.totals.kcal)} kcal · {Math.round(meal.totals.protein_g)} g de
                  proteína · {meal.items.length}{" "}
                  {meal.items.length === 1 ? "alimento" : "alimentos"}
                </p>
                <p className="mt-0.5 truncate text-xs text-neutral-500">
                  {meal.items.map((i) => i.name).join(", ")}
                </p>
              </div>
              <label className="sr-only" htmlFor={`comida-${meal.id}`}>
                Comida en la que apuntar «{meal.name}»
              </label>
              <select
                id={`comida-${meal.id}`}
                className={`${input} text-sm`}
                value={target[meal.id] ?? meal.meal_type ?? mealType}
                onChange={(e) =>
                  setTarget((prev) => ({ ...prev, [meal.id]: e.target.value as MealType }))
                }
              >
                {MEAL_TYPES.map((mt) => (
                  <option key={mt} value={mt}>
                    {MEAL_TYPE_LABELS[mt]}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={busy === meal.id}
                onClick={() => void repeat(meal)}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-[var(--color-primary)] px-4 text-sm font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] disabled:opacity-60"
              >
                <Repeat2 size={16} aria-hidden="true" /> Apuntar
              </button>
              <button
                type="button"
                disabled={busy === meal.id}
                onClick={() => void remove(meal)}
                aria-label={`Borrar «${meal.name}»`}
                className="inline-flex h-11 w-11 items-center justify-center rounded-[var(--radius-control)] text-[var(--color-muted)] hover:bg-[var(--color-surface-2)] disabled:opacity-60"
              >
                <Trash2 size={16} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Botón de «guardar esta comida», en la cabecera de cada comida del diario. */
export function SaveMealButton({
  logDate,
  mealType,
  onSaved,
}: {
  logDate: string;
  mealType: MealType;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function save() {
    const sugerido = MEAL_TYPE_LABELS[mealType];
    const name = window.prompt(
      "¿Con qué nombre la guardas? Luego la apuntas entera de un toque.",
      `Mi ${sugerido.toLowerCase()}`,
    );
    if (!name?.trim()) return;
    setBusy(true);
    try {
      await apiFetch("/api/saved-meals", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), log_date: logDate, meal_type: mealType }),
      });
      onSaved();
    } catch (err) {
      window.alert(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => void save()}
      title="Guardar esta comida para repetirla"
      className="inline-flex items-center gap-1 rounded-full border border-[var(--color-border-strong)] px-2.5 py-1 text-xs font-semibold disabled:opacity-60"
    >
      <BookmarkPlus size={13} aria-hidden="true" /> Guardar
    </button>
  );
}
