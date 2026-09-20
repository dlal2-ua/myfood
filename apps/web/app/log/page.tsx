"use client";

import { FoodImage } from "@/components/FoodImage";
import { useEffect, useRef, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { FoodSearchBox } from "@/components/FoodSearchBox";
import { MicronutrientsPanel } from "@/components/MicronutrientsPanel";
import {
  MEAL_TYPES,
  MEAL_TYPE_LABELS,
  type AiSession,
  type Favorite,
  type FoodSearchItem,
  type LogDay,
  type LogFoodEntry,
  type MealType,
  type SmartLogItem,
} from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

const SMART_LOG_MAX_POLL_ATTEMPTS = 30; // 30 × 2s = 60s
const SMART_LOG_POLL_INTERVAL_MS = 2000;

interface SmartLogReviewItem extends SmartLogItem {
  gramsInput: string;
  mealType: MealType;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function LogPage() {
  const [logDate, setLogDate] = useState(todayIso());
  const [day, setDay] = useState<LogDay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [foodNames, setFoodNames] = useState<Record<string, string>>({});

  const [selectedFood, setSelectedFood] = useState<FoodSearchItem | null>(null);
  const [mealType, setMealType] = useState<MealType>("lunch");
  const [grams, setGrams] = useState("100");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [quickAddFoodId, setQuickAddFoodId] = useState<string | null>(null);

  const [favorites, setFavorites] = useState<Favorite[]>([]);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editGrams, setEditGrams] = useState("");
  const [editMealType, setEditMealType] = useState<MealType>("lunch");
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const [smartText, setSmartText] = useState("");
  const [smartConsent, setSmartConsent] = useState(false);
  const [smartRequesting, setSmartRequesting] = useState(false);
  const [smartError, setSmartError] = useState<string | null>(null);
  const [smartWarning, setSmartWarning] = useState<string | null>(null);
  const [smartReviewItems, setSmartReviewItems] = useState<SmartLogReviewItem[]>([]);
  const [smartConfirmingIndex, setSmartConfirmingIndex] = useState<number | null>(null);
  const smartPollCountRef = useRef(0);

  useEffect(() => {
    void loadDay(logDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logDate]);

  useEffect(() => {
    apiFetch<{ items: Favorite[] }>("/api/favorites?limit=8")
      .then((res) => setFavorites(res.items))
      .catch(() => {
        // los favoritos son un atajo opcional — si falla la carga, el
        // formulario de registro normal sigue funcionando
      });
  }, []);

  function onQuickAddFromFavorite(fav: Favorite) {
    setSelectedFood({
      id: fav.food_id,
      name_es: fav.name_es,
      brand: fav.brand,
      kcal_100g: fav.kcal_100g,
      protein_100g: null,
      image_url: null,
      source: "favorite",
    });
    setGrams("100");
    setQuickAddFoodId(fav.food_id);
  }

  function onSelectFromSearch(item: FoodSearchItem) {
    setSelectedFood(item);
    setQuickAddFoodId(null);
  }

  async function loadDay(date: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<LogDay>(`/api/log?date=${date}`);
      setDay(data);
      await loadFoodNames(data.food);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadFoodNames(entries: LogFoodEntry[]) {
    const missing = [...new Set(entries.map((e) => e.food_id).filter((id): id is string => !!id))].filter(
      (id) => !(id in foodNames),
    );
    if (missing.length === 0) return;
    const pairs = await Promise.all(
      missing.map(async (id) => {
        try {
          const food = await apiFetch<{ name_es: string }>(`/api/foods/${id}`);
          return [id, food.name_es] as const;
        } catch {
          return [id, "Alimento"] as const;
        }
      }),
    );
    setFoodNames((prev) => ({ ...prev, ...Object.fromEntries(pairs) }));
  }

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedFood) {
      setAddError("Elige un alimento en el buscador.");
      return;
    }
    setAdding(true);
    setAddError(null);
    try {
      await apiFetch("/api/log/food", {
        method: "POST",
        body: JSON.stringify({
          log_date: logDate,
          meal_type: mealType,
          food_id: selectedFood.id,
          grams: Number(grams),
        }),
      });
      if (quickAddFoodId === selectedFood.id) {
        // registra el uso del favorito (no bloquea el flujo si falla)
        apiFetch(`/api/favorites/${selectedFood.id}/use`, { method: "POST" }).catch(() => {});
      }
      setSelectedFood(null);
      setQuickAddFoodId(null);
      setGrams("100");
      await loadDay(logDate);
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }

  function startEdit(entry: LogFoodEntry) {
    setEditingId(entry.id);
    setEditGrams(String(entry.grams));
    setEditMealType(entry.meal_type);
    setRowError(null);
  }

  async function onSaveEdit(entryId: string) {
    setRowBusy(entryId);
    setRowError(null);
    try {
      await apiFetch(`/api/log/food/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify({ grams: Number(editGrams), meal_type: editMealType }),
      });
      setEditingId(null);
      await loadDay(logDate);
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  async function onDelete(entryId: string) {
    setRowBusy(entryId);
    setRowError(null);
    try {
      await apiFetch(`/api/log/food/${entryId}`, { method: "DELETE" });
      await loadDay(logDate);
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  async function pollSmartLogSession(sessionId: string) {
    smartPollCountRef.current = 0;
    const tick = async () => {
      smartPollCountRef.current += 1;
      let session: AiSession;
      try {
        session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
      } catch (err) {
        setSmartError(errorMessage(err));
        return;
      }
      if (session.status === "running") {
        if (smartPollCountRef.current >= SMART_LOG_MAX_POLL_ATTEMPTS) {
          setSmartError("La interpretación está tardando más de lo esperado. Inténtalo de nuevo.");
          return;
        }
        setTimeout(() => void tick(), SMART_LOG_POLL_INTERVAL_MS);
        return;
      }
      if (session.status !== "succeeded") {
        const detail = session.validation_errors?.[0]?.message;
        setSmartError(detail ?? "No se ha podido interpretar el texto.");
        return;
      }
      const payload = session.response_payload as {
        items: SmartLogItem[];
        warning: string | null;
      } | null;
      const items = payload?.items ?? [];
      setSmartReviewItems(
        items.map((item) => ({
          ...item,
          gramsInput: String(item.grams),
          mealType: mealType,
        })),
      );
      setSmartWarning(items.length === 0 ? (payload?.warning ?? "NO_MATCH") : null);
    };
    await tick();
  }

  async function onSmartLogSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSmartRequesting(true);
    setSmartError(null);
    setSmartWarning(null);
    setSmartReviewItems([]);
    try {
      if (smartConsent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const session = await apiFetch<AiSession>("/api/log/smart", {
        method: "POST",
        body: JSON.stringify({ text: smartText }),
      });
      await pollSmartLogSession(session.id);
    } catch (err) {
      setSmartError(errorMessage(err));
    } finally {
      setSmartRequesting(false);
    }
  }

  function updateSmartReviewItem(index: number, patch: Partial<SmartLogReviewItem>) {
    setSmartReviewItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }

  function discardSmartReviewItem(index: number) {
    setSmartReviewItems((prev) => prev.filter((_, i) => i !== index));
  }

  async function confirmSmartReviewItem(index: number) {
    const item = smartReviewItems[index];
    setSmartConfirmingIndex(index);
    setSmartError(null);
    try {
      await apiFetch("/api/log/food", {
        method: "POST",
        body: JSON.stringify({
          log_date: logDate,
          meal_type: item.mealType,
          food_id: item.food_id,
          grams: Number(item.gramsInput),
        }),
      });
      discardSmartReviewItem(index);
      await loadDay(logDate);
    } catch (err) {
      setSmartError(errorMessage(err));
    } finally {
      setSmartConfirmingIndex(null);
    }
  }

  return (
    <main className="flex flex-col gap-8">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Registro diario</h1>
        <input
          type="date"
          className={inputClass}
          value={logDate}
          onChange={(e) => setLogDate(e.target.value)}
        />
      </div>

      {favorites.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-semibold">Favoritos</h2>
          <div className="flex flex-wrap gap-2">
            {favorites.map((fav) => (
              <button
                key={fav.id}
                type="button"
                onClick={() => onQuickAddFromFavorite(fav)}
                className="rounded-full border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
              >
                <span className="flex items-center gap-2">
                  <FoodImage foodId={fav.food_id} px={24} className="rounded-full" />★ {fav.name_es}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="mb-3 text-lg font-semibold">Registrar con lenguaje natural</h2>
        <p className="mb-3 text-sm text-neutral-500">
          Escribe lo que has comido, p. ej. &quot;dos huevos fritos y una tostada con
          aceite&quot;. Claude propone qué alimentos son (nunca gramos ni calorías) — tú
          revisas y ajustas antes de confirmar.
        </p>
        <form onSubmit={onSmartLogSubmit} className="flex flex-wrap items-end gap-3">
          <input
            type="text"
            required
            placeholder="dos huevos fritos y una tostada..."
            className={`${inputClass} min-w-[16rem] flex-1`}
            value={smartText}
            onChange={(e) => setSmartText(e.target.value)}
          />
          <button
            type="submit"
            disabled={smartRequesting}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
          >
            {smartRequesting ? "Interpretando…" : "Interpretar"}
          </button>
        </form>
        <label className="mt-2 flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={smartConsent}
            onChange={(e) => setSmartConsent(e.target.checked)}
            className="mt-0.5"
          />
          Acepto que este texto (sin nombre ni datos identificativos) se envíe a Claude
          para interpretarlo.
        </label>

        {smartError && <p className="mt-2 text-sm text-red-600">{smartError}</p>}
        {smartWarning && (
          <p className="mt-2 text-sm text-neutral-500">
            No se ha encontrado ningún alimento parecido en el catálogo para ese texto.
          </p>
        )}

        {smartReviewItems.length > 0 && (
          <div className="mt-4 flex flex-col gap-3">
            {smartReviewItems.map((item, index) => (
              <div
                key={`${item.food_id}-${index}`}
                className="flex flex-wrap items-end gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
              >
                <div className="min-w-[10rem]">
                  <p className="text-sm font-medium">{item.name_es}</p>
                  <p className="text-xs text-neutral-500">&quot;{item.approx_quantity_text}&quot;</p>
                </div>
                <label className="flex flex-col gap-1 text-sm">
                  Comida
                  <select
                    className={inputClass}
                    value={item.mealType}
                    onChange={(e) =>
                      updateSmartReviewItem(index, { mealType: e.target.value as MealType })
                    }
                  >
                    {MEAL_TYPES.map((mt) => (
                      <option key={mt} value={mt}>
                        {MEAL_TYPE_LABELS[mt]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  Gramos
                  <input
                    type="number"
                    min={1}
                    max={5000}
                    className={inputClass}
                    value={item.gramsInput}
                    onChange={(e) => updateSmartReviewItem(index, { gramsInput: e.target.value })}
                  />
                </label>
                <button
                  type="button"
                  disabled={smartConfirmingIndex === index}
                  onClick={() => void confirmSmartReviewItem(index)}
                  className="rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-sm text-white disabled:opacity-60"
                >
                  Confirmar
                </button>
                <button
                  type="button"
                  onClick={() => discardSmartReviewItem(index)}
                  className="text-sm text-neutral-500 underline"
                >
                  Descartar
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Registrar alimento</h2>
        <FoodSearchBox onSelect={onSelectFromSearch} />
        {selectedFood && (
          <form onSubmit={onAdd} className="mt-3 flex flex-wrap items-end gap-3">
            <p className="text-sm">
              Elegido: <span className="font-medium">{selectedFood.name_es}</span>
            </p>
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
              disabled={adding}
              className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
            >
              {adding ? "Guardando…" : "Añadir"}
            </button>
          </form>
        )}
        {addError && <p className="mt-2 text-sm text-red-600">{addError}</p>}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Entradas del {logDate}</h2>
        {loading && <p className="text-sm text-neutral-500">Cargando…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {day && (
          <>
            {day.food.length === 0 ? (
              <p className="text-sm text-neutral-500">Todavía no hay entradas para este día.</p>
            ) : (
              <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {day.food.map((entry) => (
                  <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                    {editingId === entry.id ? (
                      <div className="flex flex-wrap items-end gap-3">
                        <span className="text-sm font-medium">
                          {(entry.food_id && foodNames[entry.food_id]) || "Alimento"}
                        </span>
                        <select
                          className={inputClass}
                          value={editMealType}
                          onChange={(e) => setEditMealType(e.target.value as MealType)}
                        >
                          {MEAL_TYPES.map((mt) => (
                            <option key={mt} value={mt}>
                              {MEAL_TYPE_LABELS[mt]}
                            </option>
                          ))}
                        </select>
                        <input
                          type="number"
                          min={1}
                          max={5000}
                          className={inputClass}
                          value={editGrams}
                          onChange={(e) => setEditGrams(e.target.value)}
                        />
                        <button
                          type="button"
                          onClick={() => onSaveEdit(entry.id)}
                          disabled={rowBusy === entry.id}
                          className="rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-sm text-white disabled:opacity-60"
                        >
                          Guardar
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          className="text-sm text-neutral-500 underline"
                        >
                          Cancelar
                        </button>
                      </div>
                    ) : (
                      <>
                        <div>
                          <p className="text-sm font-medium">
                            {(entry.food_id && foodNames[entry.food_id]) || "Alimento"}
                          </p>
                          <p className="text-xs text-neutral-500">
                            {MEAL_TYPE_LABELS[entry.meal_type]} · {entry.grams} g · {entry.kcal} kcal
                          </p>
                        </div>
                        <div className="flex items-center gap-3 text-sm">
                          <button type="button" onClick={() => startEdit(entry)} className="underline">
                            Editar
                          </button>
                          <button
                            type="button"
                            onClick={() => onDelete(entry.id)}
                            disabled={rowBusy === entry.id}
                            className="text-red-600 underline disabled:opacity-60"
                          >
                            Eliminar
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {rowError && <p className="mt-2 text-sm text-red-600">{rowError}</p>}

            <div className="mt-4 flex gap-6 rounded-lg border border-neutral-200 p-4 text-sm dark:border-neutral-800">
              <div>
                <p className="text-neutral-500">Kcal</p>
                <p className="font-semibold">{day.totals.kcal}</p>
              </div>
              <div>
                <p className="text-neutral-500">Proteína</p>
                <p className="font-semibold">{day.totals.protein_g} g</p>
              </div>
              <div>
                <p className="text-neutral-500">Grasa</p>
                <p className="font-semibold">{day.totals.fat_g} g</p>
              </div>
              <div>
                <p className="text-neutral-500">Carbos</p>
                <p className="font-semibold">{day.totals.carbs_g} g</p>
              </div>
            </div>
            <MicronutrientsPanel date={logDate} />
          </>
        )}
      </section>
    </main>
  );
}
