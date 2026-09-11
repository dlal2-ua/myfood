"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import {
  MEAL_TYPES,
  MEAL_TYPE_LABELS,
  type Favorite,
  type FoodDetail,
  type LogFoodEntry,
  type MealType,
} from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function FoodDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const foodId = params.id;

  const [food, setFood] = useState<FoodDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [logDate, setLogDate] = useState(todayIso());
  const [mealType, setMealType] = useState<MealType>("lunch");
  const [grams, setGrams] = useState("100");
  const [logging, setLogging] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [logged, setLogged] = useState<LogFoodEntry | null>(null);

  const [isFavorite, setIsFavorite] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);

  useEffect(() => {
    if (!foodId) return;
    apiFetch<FoodDetail>(`/api/foods/${foodId}`)
      .then(setFood)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
    apiFetch<{ items: Favorite[] }>("/api/favorites?limit=1000")
      .then((res) => setIsFavorite(res.items.some((f) => f.food_id === foodId)))
      .catch(() => {
        // el estado de favorito es un detalle secundario — si falla, se
        // muestra el botón como "no favorito" y el usuario puede reintentar
      });
  }, [foodId]);

  async function onToggleFavorite() {
    if (!foodId) return;
    setFavoriteBusy(true);
    setFavoriteError(null);
    try {
      if (isFavorite) {
        await apiFetch(`/api/favorites/${foodId}`, { method: "DELETE" });
        setIsFavorite(false);
      } else {
        await apiFetch("/api/favorites", {
          method: "POST",
          body: JSON.stringify({ food_id: foodId }),
        });
        setIsFavorite(true);
      }
    } catch (err) {
      setFavoriteError(errorMessage(err));
    } finally {
      setFavoriteBusy(false);
    }
  }

  async function onLog(e: React.FormEvent) {
    e.preventDefault();
    setLogging(true);
    setLogError(null);
    setLogged(null);
    try {
      const entry = await apiFetch<LogFoodEntry>("/api/log/food", {
        method: "POST",
        body: JSON.stringify({
          log_date: logDate,
          meal_type: mealType,
          food_id: foodId,
          grams: Number(grams),
        }),
      });
      setLogged(entry);
      if (isFavorite) {
        // registra el uso del favorito (no bloquea el flujo si falla)
        apiFetch(`/api/favorites/${foodId}/use`, { method: "POST" }).catch(() => {});
      }
    } catch (err) {
      setLogError(errorMessage(err));
    } finally {
      setLogging(false);
    }
  }

  if (loading) return <p className="text-sm text-neutral-500">Cargando…</p>;
  if (error || !food) {
    return <p className="text-sm text-red-600">{error ?? "No se encontró el alimento."}</p>;
  }

  return (
    <main className="flex flex-col gap-6">
      <div>
        <Link href="/foods" className="text-sm text-neutral-500 underline">
          ← Volver a la búsqueda
        </Link>
        <div className="mt-2 flex items-center gap-2">
          <h1 className="text-xl font-semibold">{food.name_es}</h1>
          <button
            type="button"
            onClick={onToggleFavorite}
            disabled={favoriteBusy}
            aria-pressed={isFavorite}
            aria-label={isFavorite ? "Quitar de favoritos" : "Añadir a favoritos"}
            className="text-xl leading-none disabled:opacity-60"
            title={isFavorite ? "Quitar de favoritos" : "Añadir a favoritos"}
          >
            {isFavorite ? "★" : "☆"}
          </button>
        </div>
        {food.brand && <p className="text-sm text-neutral-500">{food.brand}</p>}
        {favoriteError && <p className="text-sm text-red-600">{favoriteError}</p>}
      </div>

      <table className="w-full max-w-sm text-sm">
        <tbody>
          <tr className="border-b border-neutral-200 dark:border-neutral-800">
            <td className="py-1 text-neutral-500">Energía</td>
            <td className="py-1 text-right">{food.kcal_100g} kcal / 100 g</td>
          </tr>
          <tr className="border-b border-neutral-200 dark:border-neutral-800">
            <td className="py-1 text-neutral-500">Proteína</td>
            <td className="py-1 text-right">{food.protein_100g} g</td>
          </tr>
          <tr className="border-b border-neutral-200 dark:border-neutral-800">
            <td className="py-1 text-neutral-500">Grasa</td>
            <td className="py-1 text-right">{food.fat_100g} g</td>
          </tr>
          <tr className="border-b border-neutral-200 dark:border-neutral-800">
            <td className="py-1 text-neutral-500">Carbohidratos</td>
            <td className="py-1 text-right">{food.carbs_100g} g</td>
          </tr>
          {food.fiber_100g != null && (
            <tr className="border-b border-neutral-200 dark:border-neutral-800">
              <td className="py-1 text-neutral-500">Fibra</td>
              <td className="py-1 text-right">{food.fiber_100g} g</td>
            </tr>
          )}
          {food.salt_100g != null && (
            <tr>
              <td className="py-1 text-neutral-500">Sal</td>
              <td className="py-1 text-right">{food.salt_100g} g</td>
            </tr>
          )}
        </tbody>
      </table>

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
          <button
            type="submit"
            disabled={logging}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
          >
            {logging ? "Guardando…" : "Registrar"}
          </button>
        </form>
        {logError && <p className="mt-2 text-sm text-red-600">{logError}</p>}
        {logged && (
          <p className="mt-2 text-sm text-[var(--color-primary)]">
            Registrado: {logged.kcal} kcal.{" "}
            <button type="button" onClick={() => router.push("/log")} className="underline">
              Ver registro del día
            </button>
          </p>
        )}
      </section>
    </main>
  );
}
