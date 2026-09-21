"use client";

import { localDateIso } from "@/lib/dates";
import { mealTypeForTime } from "@/lib/meals";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useCurrentUserId } from "@/components/CurrentUser";
import { MacroPreview, PortionPicker } from "@/components/foods/PortionPicker";
import { errorMessage } from "@/lib/api";
import { submitOrQueue } from "@/lib/offlineQueue";
import { GRAMS_KEY, amountProblem, toGrams, type Portion } from "@/lib/portions";
import {
  MEAL_TYPES,
  MEAL_TYPE_LABELS,
  type FoodDetail,
  type LogFoodEntry,
  type MealType,
} from "@/lib/types";

const inputClass =
  "h-11 rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3";

const FALLBACK_PORTION: Portion = { key: GRAMS_KEY, label: "gramos", grams: 1 };

/** Formulario de "añadir al registro diario" — compartido entre la ficha de producto
 * (`/foods/[id]`) y el flujo de escaneo (`/scan`), misma lógica en los dos sitios.
 *
 * La cantidad se elige por medida casera («1 huevo», «1 vaso») y no solo en gramos: los
 * gramos de cada medida los da el servidor en `food.portions` (R1). */
export function AddToLogForm({
  food,
  /** Adónde ir tras registrar (el flujo de escaneo vuelve al registro del día). */
  redirectTo,
}: {
  food: FoodDetail;
  redirectTo?: string;
}) {
  const router = useRouter();
  const userId = useCurrentUserId();
  const portions = food.portions?.length ? food.portions : [FALLBACK_PORTION];
  const [logDate, setLogDate] = useState(localDateIso());
  const [mealType, setMealType] = useState<MealType>(() => mealTypeForTime());
  const [portion, setPortion] = useState<Portion>(portions[0]);
  const [quantity, setQuantity] = useState(
    portions[0].key === GRAMS_KEY ? (food.default_grams ?? 100) : 1,
  );
  const [logging, setLogging] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [logged, setLogged] = useState<LogFoodEntry | null>(null);
  const [queued, setQueued] = useState(false);
  const [weighedAs, setWeighedAs] = useState<"raw" | "cooked">("raw");

  const grams = toGrams(quantity, portion);
  const problem = amountProblem(grams);

  async function onLog(e: React.FormEvent) {
    e.preventDefault();
    if (logging || problem) return;
    setLogging(true);
    setLogError(null);
    setLogged(null);
    setQueued(false);
    try {
      const outcome = await submitOrQueue<LogFoodEntry>({
        userId: userId ?? "",
        kind: "food",
        label: `${food.name_es} — ${grams} g (${MEAL_TYPE_LABELS[mealType]}, ${logDate})`,
        payload: {
          log_date: logDate,
          meal_type: mealType,
          food_id: food.id,
          grams,
          weighed_as: food.cooking_yield_factor ? weighedAs : "raw",
        },
      });
      if (outcome.queued) setQueued(true);
      else if (redirectTo) {
        router.push(redirectTo);
        return;
      } else setLogged(outcome.result);
    } catch (err) {
      setLogError(errorMessage(err));
    } finally {
      setLogging(false);
    }
  }

  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">Añadir al registro diario</h2>
      <form onSubmit={onLog} className="flex flex-col gap-3">
        <PortionPicker
          portions={portions}
          portion={portion}
          quantity={quantity}
          disabled={logging}
          onChange={({ portion: p, quantity: q }) => {
            setPortion(p);
            setQuantity(q);
          }}
        />

        <div className="flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-semibold text-[var(--color-muted)]">Fecha</span>
            <input
              type="date"
              required
              className={inputClass}
              value={logDate}
              onChange={(e) => setLogDate(e.target.value)}
            />
          </label>
          <label className="flex min-w-[8rem] flex-1 flex-col gap-1 text-sm">
            <span className="text-xs font-semibold text-[var(--color-muted)]">Comida</span>
            <select
              className={inputClass}
              value={mealType}
              onChange={(e) => setMealType(e.target.value as MealType)}
            >
              {MEAL_TYPES.map((mt) => (
                <option key={mt} value={mt}>
                  {MEAL_TYPE_LABELS[mt]}
                </option>
              ))}
            </select>
          </label>
        </div>

        {food.cooking_yield_factor ? (
          <fieldset className="flex flex-col gap-1.5 text-sm">
            <legend className="text-xs font-semibold text-[var(--color-muted)]">
              ¿Lo pesaste crudo o ya cocinado?
            </legend>
            <div className="flex gap-2">
              {(["raw", "cooked"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setWeighedAs(v)}
                  aria-pressed={weighedAs === v}
                  className={`min-h-10 flex-1 rounded-full border px-3 text-sm font-semibold ${
                    weighedAs === v
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)] text-[var(--color-primary)]"
                      : "border-[var(--color-border-strong)]"
                  }`}
                >
                  {v === "raw" ? "Crudo" : "Cocinado"}
                </button>
              ))}
            </div>
            {weighedAs === "cooked" && grams > 0 && (
              <span className="text-xs text-[var(--color-muted)]">
                ≈ {Math.round(grams / food.cooking_yield_factor)} g en crudo: se calcula sobre el
                peso crudo.
              </span>
            )}
          </fieldset>
        ) : null}

        <MacroPreview per100g={food} grams={grams} quantity={quantity} portion={portion} />

        <button
          type="submit"
          disabled={logging || problem !== null}
          className="min-h-12 self-start rounded-full bg-[var(--color-primary)] px-6 font-bold text-[var(--color-on-primary)] disabled:opacity-60 hover:bg-[var(--color-primary-hover)]"
        >
          {logging ? "Guardando…" : "Registrar"}
        </button>
      </form>
      {logError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{logError}</p>}
      {queued && (
        <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">
          Sin conexión: guardado en este dispositivo. Se registrará solo al volver la red.
        </p>
      )}
      {logged && (
        <p className="mt-2 text-sm text-[var(--color-primary)]">
          Registrado: {logged.kcal} kcal.{" "}
          <button type="button" onClick={() => router.push("/log")} className="underline">
            Ver registro del día
          </button>
        </p>
      )}
    </section>
  );
}
