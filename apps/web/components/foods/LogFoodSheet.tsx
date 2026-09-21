"use client";

import { Star } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useCurrentUserId } from "@/components/CurrentUser";
import { FoodImage } from "@/components/FoodImage";
import { MacroPreview, PortionPicker } from "@/components/foods/PortionPicker";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { Skeleton } from "@/components/ui/states";
import { apiFetch, errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import { brandLabel } from "@/lib/foodDisplay";
import { mealTypeForTime } from "@/lib/meals";
import { submitOrQueue } from "@/lib/offlineQueue";
import { GRAMS_KEY, toGrams, type Portion } from "@/lib/portions";
import { MEAL_TYPES, MEAL_TYPE_LABELS, type FoodDetail, type MealType } from "@/lib/types";

const FALLBACK_PORTION: Portion = { key: GRAMS_KEY, label: "gramos", grams: 1 };

/** Registrar un alimento sin salir de la lista, como en Fitia o MyFitnessPal: se elige la
 * medida y la comida en una hoja y se añade ahí mismo.
 *
 * Antes había que entrar en la ficha del alimento y volver, lo que convertía apuntar tres
 * cosas del desayuno en seis cambios de pantalla. */
export function LogFoodSheet({
  foodId,
  foodName,
  date,
  mealType: initialMeal,
  onClose,
  onLogged,
}: {
  foodId: string | null;
  foodName?: string;
  /** Día al que se añade; por defecto, hoy. */
  date?: string;
  mealType?: MealType;
  onClose: () => void;
  onLogged?: () => void;
}) {
  const userId = useCurrentUserId();
  const [food, setFood] = useState<FoodDetail | null>(null);
  const [portion, setPortion] = useState<Portion>(FALLBACK_PORTION);
  const [quantity, setQuantity] = useState(100);
  const [mealType, setMealType] = useState<MealType>(() => initialMeal ?? mealTypeForTime());
  const [weighedAs, setWeighedAs] = useState<"raw" | "cooked">("raw");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [favorite, setFavorite] = useState(false);

  const logDate = date ?? localDateIso();

  useEffect(() => {
    if (!foodId) return;
    setFood(null);
    setError(null);
    setDone(null);
    setFavorite(false);
    let cancelled = false;
    apiFetch<FoodDetail>(`/api/foods/${foodId}`)
      .then((detail) => {
        if (cancelled) return;
        setFood(detail);
        const first = detail.portions?.[0] ?? FALLBACK_PORTION;
        setPortion(first);
        setQuantity(first.key === GRAMS_KEY ? (detail.default_grams ?? 100) : 1);
      })
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [foodId]);

  useEffect(() => {
    if (initialMeal) setMealType(initialMeal);
  }, [initialMeal]);

  const grams = toGrams(quantity, portion);

  async function onAdd() {
    if (!food || grams <= 0) return;
    setSaving(true);
    setError(null);
    try {
      const outcome = await submitOrQueue({
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
      setDone(
        outcome.queued
          ? "Sin conexión: guardado aquí y se registrará al volver la red."
          : `Añadido a ${MEAL_TYPE_LABELS[mealType].toLowerCase()}.`,
      );
      onLogged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function toggleFavorite() {
    if (!food) return;
    const next = !favorite;
    setFavorite(next);
    try {
      if (next) {
        await apiFetch("/api/favorites", {
          method: "POST",
          body: JSON.stringify({ food_id: food.id }),
        });
      } else {
        await apiFetch(`/api/favorites/${food.id}`, { method: "DELETE" });
      }
    } catch {
      setFavorite(!next); // no se pudo guardar: la estrella vuelve a como estaba
    }
  }

  return (
    <BottomSheet
      open={foodId !== null}
      onClose={onClose}
      title={food?.name_es ?? foodName ?? "Añadir al diario"}
    >
      {!food ? (
        error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : (
          <Skeleton lines={5} />
        )
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <FoodImage foodId={food.id} size={200} px={56} className="rounded-2xl" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-[var(--color-muted)]">
                {brandLabel(food.brand, null) ?? food.category ?? "Alimento"}
              </p>
              <Link href={`/foods/${food.id}`} className="text-xs font-semibold underline">
                Ver la ficha completa
              </Link>
            </div>
            <button
              type="button"
              onClick={() => void toggleFavorite()}
              aria-pressed={favorite}
              aria-label={favorite ? "Quitar de favoritos" : "Guardar en favoritos"}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-[var(--color-border-strong)]"
            >
              <Star
                size={18}
                aria-hidden="true"
                className={favorite ? "fill-[var(--color-primary)] text-[var(--color-primary)]" : ""}
              />
            </button>
          </div>

          <PortionPicker
            portions={food.portions?.length ? food.portions : [FALLBACK_PORTION]}
            portion={portion}
            quantity={quantity}
            disabled={saving}
            onChange={({ portion: p, quantity: q }) => {
              setPortion(p);
              setQuantity(q);
              setDone(null);
            }}
          />

          <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-[var(--color-muted)]">Comida</span>
            <select
              value={mealType}
              disabled={saving}
              onChange={(e) => setMealType(e.target.value as MealType)}
              className="h-11 rounded-[var(--radius-control)] px-3 text-sm font-semibold"
            >
              {MEAL_TYPES.map((mt) => (
                <option key={mt} value={mt}>
                  {MEAL_TYPE_LABELS[mt]}
                </option>
              ))}
            </select>
          </label>

          {food.cooking_yield_factor ? (
            <fieldset className="flex flex-col gap-1.5">
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
            </fieldset>
          ) : null}

          <MacroPreview per100g={food} grams={grams} quantity={quantity} portion={portion} />

          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          {done && <p className="text-sm font-semibold text-[var(--color-primary)]">{done}</p>}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="min-h-12 flex-1 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold"
            >
              {done ? "Cerrar" : "Cancelar"}
            </button>
            <button
              type="button"
              onClick={() => void onAdd()}
              disabled={saving || grams <= 0}
              className="min-h-12 flex-[2] rounded-full bg-[var(--color-primary)] text-sm font-bold text-[var(--color-on-primary)] disabled:opacity-60"
            >
              {saving ? "Guardando…" : done ? "Añadir otra vez" : "Añadir al diario"}
            </button>
          </div>
        </div>
      )}
    </BottomSheet>
  );
}
