"use client";

import { FoodImage } from "@/components/FoodImage";
import { FoodSearchBox } from "@/components/FoodSearchBox";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { MEAL_TYPE_LABELS } from "@/lib/types";
import type {
  DietPlanDetail,
  DietPlanStatus,
  FoodSearchItem,
  MealType,
  PlanItem,
  RecipeSummary,
} from "@/lib/types";

export default function DietPlanDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const planId = params.id;

  const [plan, setPlan] = useState<DietPlanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [openItemId, setOpenItemId] = useState<string | null>(null);
  const [editGrams, setEditGrams] = useState("");
  const [changingFood, setChangingFood] = useState(false);

  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [batchCookMealId, setBatchCookMealId] = useState<string | null>(null);
  const [batchRecipeId, setBatchRecipeId] = useState("");
  const [batchServings, setBatchServings] = useState("1");
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);

  async function load() {
    if (!planId) return;
    setLoading(true);
    setError(null);
    try {
      setPlan(await apiFetch<DietPlanDetail>(`/api/diet-plans/${planId}`));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    apiFetch<RecipeSummary[]>("/api/recipes")
      .then(setRecipes)
      .catch(() => {
        // El batch cooking es un atajo opcional; si falla la lista de
        // recetas, el resto de la página del plan sigue funcionando.
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  async function onBatchCook(dayIndex: number, mealType: MealType) {
    if (!batchRecipeId || !batchServings) return;
    setBatchBusy(true);
    setBatchError(null);
    try {
      await apiFetch(`/api/diet-plans/${planId}/batch-cook`, {
        method: "POST",
        body: JSON.stringify({
          recipe_id: batchRecipeId,
          assignments: [
            { day_index: dayIndex, meal_type: mealType, servings: Number(batchServings) },
          ],
        }),
      });
      setBatchCookMealId(null);
      setBatchRecipeId("");
      setBatchServings("1");
      await load();
    } catch (err) {
      setBatchError(errorMessage(err));
    } finally {
      setBatchBusy(false);
    }
  }

  async function onStatusChange(status: DietPlanStatus) {
    try {
      await apiFetch(`/api/diet-plans/${planId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function onDelete() {
    try {
      await apiFetch(`/api/diet-plans/${planId}`, { method: "DELETE" });
      router.push("/diet-plans");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function onSubstitute(item: PlanItem, alternativeId: string) {
    setBusyItemId(item.id);
    try {
      await apiFetch(`/api/diet-plans/${planId}/items/${item.id}/substitute`, {
        method: "POST",
        body: JSON.stringify({ alternative_id: alternativeId }),
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyItemId(null);
    }
  }

  async function onEditItem(item: PlanItem, body: { food_id?: string; grams?: number }) {
    setBusyItemId(item.id);
    setError(null);
    try {
      await apiFetch(`/api/diet-plans/${planId}/items/${item.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setOpenItemId(null);
      setChangingFood(false);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyItemId(null);
    }
  }

  function toggleItem(item: PlanItem) {
    setChangingFood(false);
    setEditGrams(String(item.grams));
    setOpenItemId(openItemId === item.id ? null : item.id);
  }

  if (loading) return <p className="text-sm text-neutral-500">Cargando…</p>;
  if (error || !plan) {
    return <p className="text-sm text-red-600">{error ?? "No se encontró el plan."}</p>;
  }

  return (
    <main className="flex flex-col gap-6">
      <div>
        <Link href="/diet-plans" className="text-sm text-neutral-500 underline">
          ← Volver a planes
        </Link>
        <div className="mt-2 flex items-center justify-between">
          <h1 className="text-xl font-semibold">{plan.name}</h1>
          <span className="text-xs uppercase text-neutral-500">{plan.status}</span>
        </div>
        <p className="text-sm text-neutral-500">
          Objetivo diario: {plan.target_kcal} kcal · {plan.target_protein_g} g prot. ·{" "}
          {plan.target_fat_g} g grasa · {plan.target_carbs_g} g carbs
        </p>
        <div className="mt-2 flex gap-3 text-sm">
          {plan.status !== "active" && (
            <button type="button" onClick={() => onStatusChange("active")} className="underline">
              Marcar activo
            </button>
          )}
          {plan.status !== "archived" && (
            <button type="button" onClick={() => onStatusChange("archived")} className="underline">
              Archivar
            </button>
          )}
          <button type="button" onClick={onDelete} className="text-red-600 underline">
            Eliminar
          </button>
        </div>
      </div>

      {plan.days.map((day) => (
        <section key={day.id} className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Día {day.day_index + 1}</h2>
            <span className="text-sm text-neutral-500">
              {day.totals.kcal} kcal · {day.totals.protein_g}g P · {day.totals.fat_g}g G ·{" "}
              {day.totals.carbs_g}g C
            </span>
          </div>
          {day.warning === "TARGETS_NOT_MET" && (
            <p className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
              Con los alimentos disponibles este día queda a más de un 5 % de tu objetivo de
              calorías ({plan.target_kcal} kcal). Puedes ajustar los gramos a mano.
            </p>
          )}
          {!day.is_optimal && (
            <p className="mb-3 text-xs text-neutral-500">
              El cálculo se cortó por tiempo: es la mejor solución encontrada, no necesariamente
              la óptima.
            </p>
          )}
          <div className="flex flex-col gap-4">
            {day.meals.map((meal) => (
              <div key={meal.id}>
                <h3 className="mb-1 text-sm font-semibold text-neutral-500">
                  {MEAL_TYPE_LABELS[meal.meal_type] ?? meal.meal_type}
                </h3>
                <ul className="flex flex-col gap-1">
                  {meal.items.map((item) => (
                    <li key={item.id} className="flex flex-col gap-2 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="flex items-center gap-2">
                          {item.food_id && <FoodImage foodId={item.food_id} px={32} />}
                          {item.name_es ?? "(alimento eliminado)"} — {item.grams} g
                        </span>
                        {item.food_id && (
                          <button
                            type="button"
                            onClick={() => toggleItem(item)}
                            aria-expanded={openItemId === item.id}
                            className="rounded border border-neutral-300 px-2 py-0.5 text-xs dark:border-neutral-700"
                          >
                            {openItemId === item.id ? "Cerrar" : "Cambiar"}
                          </button>
                        )}
                      </div>
                      {openItemId === item.id && (
                        <div className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                          {item.alternatives.length > 0 ? (
                            <div>
                              <p className="mb-2 text-xs font-semibold text-neutral-500">
                                Alternativas del mismo tipo, con los gramos ya ajustados para
                                conservar las calorías
                              </p>
                              <ul className="flex flex-col gap-2">
                                {item.alternatives.map((alt) => (
                                  <li key={alt.id} className="flex items-center gap-2">
                                    <FoodImage foodId={alt.food_id} px={40} />
                                    <span className="flex-1">
                                      {alt.name_es} — {alt.grams} g
                                    </span>
                                    <button
                                      type="button"
                                      disabled={busyItemId === item.id}
                                      onClick={() => onSubstitute(item, alt.id)}
                                      className="rounded bg-[var(--color-primary)] px-2 py-1 text-xs text-white disabled:opacity-60"
                                    >
                                      Usar
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : (
                            <p className="text-xs text-neutral-500">
                              No hay alternativas del mismo tipo con tus restricciones.
                            </p>
                          )}
                          <div className="flex flex-wrap items-end gap-2">
                            <label className="flex flex-col gap-1 text-xs">
                              Gramos
                              <input
                                type="number"
                                min={1}
                                max={2000}
                                value={editGrams}
                                onChange={(e) => setEditGrams(e.target.value)}
                                className="w-24 rounded border border-neutral-300 px-2 py-1 dark:border-neutral-700 dark:bg-neutral-900"
                              />
                            </label>
                            <button
                              type="button"
                              disabled={busyItemId === item.id || !Number(editGrams)}
                              onClick={() => onEditItem(item, { grams: Number(editGrams) })}
                              className="rounded border border-neutral-300 px-2 py-1 text-xs disabled:opacity-60 dark:border-neutral-700"
                            >
                              Guardar gramos
                            </button>
                            <button
                              type="button"
                              onClick={() => setChangingFood(!changingFood)}
                              className="text-xs text-neutral-500 underline"
                            >
                              {changingFood ? "Cancelar" : "Elegir otro alimento"}
                            </button>
                          </div>
                          {changingFood && (
                            <FoodSearchBox
                              onSelect={(food: FoodSearchItem) =>
                                onEditItem(item, { food_id: food.id })
                              }
                            />
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
                {recipes.length > 0 && (
                  <div className="mt-2">
                    {batchCookMealId === meal.id ? (
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <select
                          value={batchRecipeId}
                          onChange={(e) => setBatchRecipeId(e.target.value)}
                          className="rounded border border-neutral-300 px-2 py-1 dark:border-neutral-700 dark:bg-neutral-900"
                        >
                          <option value="">Elige una receta…</option>
                          {recipes.map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.name}
                            </option>
                          ))}
                        </select>
                        <input
                          type="number"
                          min={1}
                          value={batchServings}
                          onChange={(e) => setBatchServings(e.target.value)}
                          className="w-16 rounded border border-neutral-300 px-2 py-1 dark:border-neutral-700 dark:bg-neutral-900"
                        />
                        <span className="text-neutral-400">raciones</span>
                        <button
                          type="button"
                          disabled={batchBusy || !batchRecipeId}
                          onClick={() => onBatchCook(day.day_index, meal.meal_type)}
                          className="rounded bg-[var(--color-primary)] px-2 py-1 text-white disabled:opacity-60"
                        >
                          {batchBusy ? "Asignando…" : "Asignar"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setBatchCookMealId(null)}
                          className="text-neutral-400 underline"
                        >
                          Cancelar
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setBatchCookMealId(meal.id)}
                        className="text-xs text-neutral-500 underline"
                      >
                        🍲 Asignar receta de batch cooking
                      </button>
                    )}
                    {batchError && batchCookMealId === meal.id && (
                      <p className="mt-1 text-xs text-red-600">{batchError}</p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
