"use client";

import { FoodImage } from "@/components/FoodImage";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { FoodSearchBox } from "@/components/FoodSearchBox";
import { ReceiptScanPanel } from "@/components/ReceiptScanPanel";
import type { FoodSearchItem, PantryItem } from "@/lib/types";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

export default function PantryPage() {
  const [items, setItems] = useState<PantryItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedFood, setSelectedFood] = useState<FoodSearchItem | null>(null);
  const [quantity, setQuantity] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await apiFetch<PantryItem[]>("/api/pantry"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedFood || !quantity) {
      setAddError("Elige un alimento y una cantidad.");
      return;
    }
    setAdding(true);
    setAddError(null);
    try {
      await apiFetch("/api/pantry", {
        method: "POST",
        body: JSON.stringify({
          food_id: selectedFood.id,
          quantity_g: Number(quantity),
          expires_on: expiresOn || null,
        }),
      });
      setSelectedFood(null);
      setQuantity("");
      setExpiresOn("");
      await load();
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }

  async function onDelete(itemId: string) {
    setRowBusy(itemId);
    setRowError(null);
    try {
      await apiFetch(`/api/pantry/${itemId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  return (
    <main className="flex flex-col gap-8">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Despensa</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Lo que ya tienes en casa. Al generar la lista de la compra desde un plan, se descuenta
          automáticamente lo que aparece aquí.
        </p>
      </div>

      <ReceiptScanPanel onAdded={load} />

      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Añadir a la despensa</h2>
        <FoodSearchBox onSelect={setSelectedFood} />
        {selectedFood && (
          <form onSubmit={onAdd} className="flex flex-wrap items-end gap-3">
            <p className="text-sm">
              Elegido: <span className="font-medium">{selectedFood.name_es}</span>
            </p>
            <label className="flex flex-col gap-1 text-sm">
              Cantidad (g)
              <input
                type="number"
                min={1}
                className={inputClass}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Caduca (opcional)
              <input
                type="date"
                className={inputClass}
                value={expiresOn}
                onChange={(e) => setExpiresOn(e.target.value)}
              />
            </label>
            <button
              type="submit"
              disabled={adding || !quantity}
              className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
            >
              {adding ? "Añadiendo…" : "Añadir"}
            </button>
          </form>
        )}
        {addError && <p className="text-sm text-red-600 dark:text-red-400">{addError}</p>}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Tu despensa</h2>
        {loading && <Skeleton lines={3} />}
        {error && <ErrorState message={error} onRetry={() => void load()} />}
        {items && (
          <>
            {items.length === 0 ? (
              <EmptyState message="Tu despensa está vacía. Añade lo que tienes en casa para que la lista de la compra lo descuente." />
            ) : (
              <ul className="divide-y divide-[var(--color-border)]">
                {items.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-2 py-3"
                  >
                    <span className="flex items-center gap-3 text-sm">
                      <FoodImage foodId={item.food_id} px={36} />
                      {item.food_name} · {item.quantity_g} g
                      {item.expires_on && ` · caduca ${item.expires_on}`}
                      {!item.is_mine && (
                        <span className="ml-2 text-xs text-neutral-400">de {item.owner_name}</span>
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={() => onDelete(item.id)}
                      disabled={rowBusy === item.id || !item.is_mine}
                      title={!item.is_mine ? "Solo puedes editar tu propia despensa" : undefined}
                      className="text-sm text-red-600 dark:text-red-400 underline disabled:opacity-30"
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
