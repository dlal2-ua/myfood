"use client";

import { localDateIso } from "@/lib/dates";
import { mealTypeForTime } from "@/lib/meals";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useCurrentUserId } from "@/components/CurrentUser";
import { errorMessage } from "@/lib/api";
import { submitOrQueue } from "@/lib/offlineQueue";
import { MEAL_TYPES, MEAL_TYPE_LABELS, type LogFoodEntry, type MealType } from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

function todayIso(): string {
  return localDateIso();
}

/** Formulario de "añadir al registro diario" — compartido entre la ficha de
 * producto (`/foods/[id]`) y el flujo de escaneo (`/scan`), misma lógica en
 * los dos sitios. */
export function AddToLogForm({
  foodId,
  foodName,
  servingSizeG,
  servingLabel,
  cookingYieldFactor,
  redirectTo,
}: {
  foodId: string;
  foodName?: string;
  /** Porción habitual del producto: es la cantidad por defecto (y un atajo). */
  servingSizeG?: number | null;
  servingLabel?: string | null;
  /** gramos cocido / gramos crudo: si el alimento lo tiene, se puede indicar que se pesó cocinado. */
  cookingYieldFactor?: number | null;
  /** Adónde ir tras registrar (el flujo de escaneo vuelve al registro del día). */
  redirectTo?: string;
}) {
  const router = useRouter();
  const userId = useCurrentUserId();
  const [logDate, setLogDate] = useState(todayIso());
  const [mealType, setMealType] = useState<MealType>(() => mealTypeForTime());
  const [grams, setGrams] = useState(String(servingSizeG && servingSizeG > 0 ? servingSizeG : 100));
  const [logging, setLogging] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [logged, setLogged] = useState<LogFoodEntry | null>(null);
  const [queued, setQueued] = useState(false);
  const [weighedAs, setWeighedAs] = useState<"raw" | "cooked">("raw");

  async function onLog(e: React.FormEvent) {
    e.preventDefault();
    setLogging(true);
    setLogError(null);
    setLogged(null);
    setQueued(false);
    try {
      const outcome = await submitOrQueue<LogFoodEntry>({
        userId: userId ?? "",
        kind: "food",
        label: `${foodName ?? "Alimento"} — ${Number(grams)} g (${MEAL_TYPE_LABELS[mealType]}, ${logDate})`,
        payload: {
          log_date: logDate,
          meal_type: mealType,
          food_id: foodId,
          grams: Number(grams),
          weighed_as: cookingYieldFactor ? weighedAs : "raw",
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
      <form onSubmit={onLog} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Fecha
          <input
            type="date"
            required
            className={inputClass}
            value={logDate}
            onChange={(e) => setLogDate(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Comida
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
        <label className="flex flex-col gap-1 text-sm">
          Cantidad (g)
          <input
            type="number"
            required
            min={1}
            max={5000}
            className={inputClass}
            value={grams}
            onChange={(e) => setGrams(e.target.value)}
          />
        </label>
        {cookingYieldFactor ? (
          <fieldset className="flex flex-col gap-1 text-sm">
            <legend className="mb-1">¿Lo pesaste crudo o ya cocinado?</legend>
            <div className="flex gap-3">
              {(["raw", "cooked"] as const).map((v) => (
                <label key={v} className="flex items-center gap-1">
                  <input
                    type="radio"
                    name="weighed-as"
                    checked={weighedAs === v}
                    onChange={() => setWeighedAs(v)}
                  />
                  {v === "raw" ? "Crudo" : "Cocinado"}
                </label>
              ))}
            </div>
            {weighedAs === "cooked" && Number(grams) > 0 && (
              <span className="text-xs text-neutral-500">
                ≈ {Math.round(Number(grams) / cookingYieldFactor)} g en crudo: se calcula sobre el peso
                crudo.
              </span>
            )}
          </fieldset>
        ) : null}
        {servingSizeG && servingSizeG > 0 ? (
          <button
            type="button"
            onClick={() => setGrams(String(servingSizeG))}
            className="rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700"
            title="Usar la porción indicada en el envase"
          >
            1 porción ({servingSizeG} g{servingLabel ? ` · ${servingLabel}` : ""})
          </button>
        ) : null}
        <button
          type="submit"
          disabled={logging}
          className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
        >
          {logging ? "Guardando…" : "Registrar"}
        </button>
      </form>
      {logError && <p className="mt-2 text-sm text-red-600">{logError}</p>}
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
