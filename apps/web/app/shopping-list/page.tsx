"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { FoodSearchBox } from "@/components/FoodSearchBox";
import type { DietPlan, FoodSearchItem, ShoppingList, ShoppingListItem } from "@/lib/types";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

export default function ShoppingListPage() {
  const [list, setList] = useState<ShoppingList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [freeText, setFreeText] = useState("");
  const [freeTextCategory, setFreeTextCategory] = useState("");
  const [addingText, setAddingText] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);

  const [selectedFood, setSelectedFood] = useState<FoodSearchItem | null>(null);
  const [foodQuantity, setFoodQuantity] = useState("");
  const [foodCategory, setFoodCategory] = useState("");
  const [addingFood, setAddingFood] = useState(false);
  const [foodError, setFoodError] = useState<string | null>(null);

  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const [plans, setPlans] = useState<DietPlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  useEffect(() => {
    void load();
    void loadPlans();
  }, []);

  async function loadPlans() {
    try {
      setPlans(await apiFetch<DietPlan[]>("/api/diet-plans"));
    } catch {
      // La lista de planes es un atajo opcional; si falla, la lista de la
      // compra manual sigue funcionando igual.
    }
  }

  async function onGenerateFromPlan() {
    if (!selectedPlanId) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      await apiFetch(`/api/shopping-list/from-plan/${selectedPlanId}`, { method: "POST" });
      await load();
    } catch (err) {
      setGenerateError(errorMessage(err));
    } finally {
      setGenerating(false);
    }
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<ShoppingList>("/api/shopping-list");
      setList(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function onAddFreeText(e: React.FormEvent) {
    e.preventDefault();
    if (!freeText.trim()) return;
    setAddingText(true);
    setTextError(null);
    try {
      await apiFetch("/api/shopping-list", {
        method: "POST",
        body: JSON.stringify({
          free_text: freeText.trim(),
          category: freeTextCategory.trim() || null,
        }),
      });
      setFreeText("");
      setFreeTextCategory("");
      await load();
    } catch (err) {
      setTextError(errorMessage(err));
    } finally {
      setAddingText(false);
    }
  }

  async function onAddFood(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedFood) {
      setFoodError("Elige un alimento en el buscador.");
      return;
    }
    setAddingFood(true);
    setFoodError(null);
    try {
      await apiFetch("/api/shopping-list", {
        method: "POST",
        body: JSON.stringify({
          food_id: selectedFood.id,
          quantity_g: foodQuantity ? Number(foodQuantity) : null,
          category: foodCategory.trim() || null,
        }),
      });
      setSelectedFood(null);
      setFoodQuantity("");
      setFoodCategory("");
      await load();
    } catch (err) {
      setFoodError(errorMessage(err));
    } finally {
      setAddingFood(false);
    }
  }

  async function onToggleChecked(item: ShoppingListItem) {
    setRowBusy(item.id);
    setRowError(null);
    try {
      await apiFetch(`/api/shopping-list/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_checked: !item.is_checked }),
      });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  async function onDelete(itemId: string) {
    setRowBusy(itemId);
    setRowError(null);
    try {
      await apiFetch(`/api/shopping-list/${itemId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  async function onClearChecked() {
    setClearing(true);
    setRowError(null);
    try {
      await apiFetch("/api/shopping-list/checked", { method: "DELETE" });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setClearing(false);
    }
  }

  const hasChecked = list?.items.some((i) => i.is_checked) ?? false;

  return (
    <main className="flex flex-col gap-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Lista de la compra</h1>

      {plans.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold">Generar desde un plan</h2>
          <p className="text-sm text-neutral-500">
            Suma lo que necesitas para los 7 días del plan y descuenta lo que ya tienes en la{" "}
            <a href="/pantry" className="underline">
              despensa
            </a>
            . Repetirlo para el mismo plan regenera la lista en limpio.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <select
              className={inputClass}
              value={selectedPlanId}
              onChange={(e) => setSelectedPlanId(e.target.value)}
            >
              <option value="">Elige un plan…</option>
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={onGenerateFromPlan}
              disabled={generating || !selectedPlanId}
              className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
            >
              {generating ? "Generando…" : "Generar lista"}
            </button>
          </div>
          {generateError && <p className="text-sm text-red-600 dark:text-red-400">{generateError}</p>}
        </section>
      )}

      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Añadir artículo</h2>

        <form onSubmit={onAddFreeText} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Texto libre
            <input
              type="text"
              placeholder="p. ej. Papel de aluminio"
              className={inputClass}
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Categoría (opcional)
            <input
              type="text"
              className={inputClass}
              value={freeTextCategory}
              onChange={(e) => setFreeTextCategory(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={addingText || !freeText.trim()}
            className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {addingText ? "Añadiendo…" : "Añadir texto"}
          </button>
        </form>
        {textError && <p className="text-sm text-red-600 dark:text-red-400">{textError}</p>}

        <div>
          <p className="mb-2 text-sm text-neutral-500">O elige un alimento del catálogo:</p>
          <FoodSearchBox onSelect={setSelectedFood} />
          {selectedFood && (
            <form onSubmit={onAddFood} className="mt-3 flex flex-wrap items-end gap-3">
              <p className="text-sm">
                Elegido: <span className="font-medium">{selectedFood.name_es}</span>
              </p>
              <label className="flex flex-col gap-1 text-sm">
                Cantidad (g, opcional)
                <input
                  type="number"
                  min={1}
                  className={inputClass}
                  value={foodQuantity}
                  onChange={(e) => setFoodQuantity(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Categoría (opcional)
                <input
                  type="text"
                  className={inputClass}
                  value={foodCategory}
                  onChange={(e) => setFoodCategory(e.target.value)}
                />
              </label>
              <button
                type="submit"
                disabled={addingFood}
                className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
              >
                {addingFood ? "Añadiendo…" : "Añadir alimento"}
              </button>
            </form>
          )}
          {foodError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{foodError}</p>}
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Tu lista</h2>
          {hasChecked && (
            <button
              type="button"
              onClick={onClearChecked}
              disabled={clearing}
              className="text-sm text-neutral-500 underline disabled:opacity-60"
            >
              {clearing ? "Limpiando…" : "Limpiar completados"}
            </button>
          )}
        </div>
        {loading && <Skeleton lines={3} />}
        {error && <ErrorState message={error} onRetry={() => void load()} />}
        {list && (
          <>
            {list.items.length === 0 ? (
              <EmptyState message="Tu lista de la compra está vacía. Genérala desde un plan o añade productos a mano." />
            ) : (
              <ul className="divide-y divide-[var(--color-border)]">
                {list.items.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-2 py-3"
                  >
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={item.is_checked}
                        onChange={() => onToggleChecked(item)}
                        disabled={rowBusy === item.id}
                      />
                      <span className={item.is_checked ? "text-neutral-400 line-through" : ""}>
                        {item.food_name ?? item.free_text}
                        {item.quantity_g != null && ` · ${item.quantity_g} g`}
                        {item.category && ` · ${item.category}`}
                        {!item.is_mine && (
                          <span className="ml-2 text-xs text-neutral-400">de {item.owner_name}</span>
                        )}
                      </span>
                    </label>
                    <button
                      type="button"
                      onClick={() => onDelete(item.id)}
                      disabled={rowBusy === item.id}
                      className="text-sm text-red-600 dark:text-red-400 underline disabled:opacity-60"
                    >
                      Eliminar
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {rowError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{rowError}</p>}
          </>
        )}
      </section>
    </main>
  );
}
