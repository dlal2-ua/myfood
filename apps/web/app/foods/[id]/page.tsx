"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AddToLogForm } from "@/components/AddToLogForm";
import { apiFetch, errorMessage } from "@/lib/api";
import type { FoodDetail } from "@/lib/types";

export default function FoodDetailPage() {
  const params = useParams<{ id: string }>();
  const foodId = params.id;

  const [food, setFood] = useState<FoodDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!foodId) return;
    apiFetch<FoodDetail>(`/api/foods/${foodId}`)
      .then(setFood)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [foodId]);

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
        <h1 className="mt-2 text-xl font-semibold">{food.name_es}</h1>
        {food.brand && <p className="text-sm text-neutral-500">{food.brand}</p>}
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

      <AddToLogForm foodId={food.id} />
    </main>
  );
}
