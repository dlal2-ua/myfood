"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { AddToLogForm } from "@/components/AddToLogForm";
import { apiFetch, errorMessage } from "@/lib/api";
import type { Favorite, FoodDetail } from "@/lib/types";

export default function FoodDetailPage() {
  const params = useParams<{ id: string }>();
  const foodId = params.id;

  const [food, setFood] = useState<FoodDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Alérgenos</h2>
        {food.allergens.length === 0 ? (
          <p className="text-sm text-neutral-500">
            Sin alérgenos registrados para este alimento (no es una garantía: revisa la etiqueta).
          </p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {food.allergens.map((a) => (
              <li
                key={a.code}
                className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
                title={
                  a.origin === "declared"
                    ? "Declarado por el fabricante"
                    : a.origin === "trace"
                      ? "Puede contener trazas"
                      : "Inferido por el nombre del alimento (orientativo)"
                }
              >
                {a.name_es}
                {a.origin === "trace" && " (trazas)"}
                {a.origin === "inferred" && " (estimado)"}
              </li>
            ))}
          </ul>
        )}
        <MedicalDisclaimer>
          Información de alérgenos orientativa. Revisa siempre la etiqueta del producto.
        </MedicalDisclaimer>
      </section>

      <AddToLogForm foodId={food.id} />
    </main>
  );
}
