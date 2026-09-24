"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { DayPager } from "@/components/DayPager";
import { localDateIso } from "@/lib/dates";
import { groupByMeal } from "@/lib/today";
import { mealTypeForTime } from "@/lib/meals";
import { FoodImage } from "@/components/FoodImage";
import { useEffect, useRef, useState } from "react";
import { useCurrentUserId } from "@/components/CurrentUser";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import {
  AiWaiting,
  QuotaBadge,
  ThinkingDots,
  useAiQuota,
  useElapsedSeconds,
} from "@/components/ui/AiWaiting";
import { QUEUE_FLUSHED_EVENT, submitOrQueue } from "@/lib/offlineQueue";
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
  type FoodOrigin,
  type QuantityKind,
  type SmartLogAlternative,
  type SmartLogItem,
  type SmartLogResult,
} from "@/lib/types";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

const ORIGIN_LABELS: Record<FoodOrigin, string> = {
  casero: "casero",
  envasado: "de paquete",
  restaurante: "de restaurante",
  desconocido: "origen sin determinar",
};

const QUANTITY_LABELS: Partial<Record<QuantityKind, string>> = {
  porcion: "porción",
  racion: "ración",
  punado: "puñado",
  cucharadita: "cucharadita",
};

/** «1 porción grande» — lo que el modelo entendió, para poder juzgar el gramaje de un vistazo
 * en vez de aceptar un número a ciegas. */
function describeInterpretation(item: SmartLogItem): string | null {
  if (!item.tipo_cantidad) return null;
  const unit = QUANTITY_LABELS[item.tipo_cantidad] ?? item.tipo_cantidad;
  const size =
    item.tamano && item.tamano !== "mediano"
      ? item.tamano === "grande"
        ? " grande"
        : " pequeña"
      : "";
  return `${unit}${size}`;
}

const SMART_LOG_MAX_POLL_ATTEMPTS = 30; // 30 × 2s = 60s
const SMART_LOG_POLL_INTERVAL_MS = 2000;

interface SmartLogReviewItem extends SmartLogItem {
  gramsInput: string;
  mealType: MealType;
}

function todayIso(): string {
  return localDateIso();
}

export default function LogPage() {
  const userId = useCurrentUserId();
  const [queuedNote, setQueuedNote] = useState<string | null>(null);
  const [logDate, setLogDate] = useState(todayIso());
  const [day, setDay] = useState<LogDay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [foodNames, setFoodNames] = useState<Record<string, string>>({});

  const [selectedFood, setSelectedFood] = useState<FoodSearchItem | null>(null);
  const [mealType, setMealType] = useState<MealType>(() => mealTypeForTime());

  // `/log?meal=lunch` (desde el «+» de cada comida de Hoy) deja esa comida preseleccionada.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("meal");
    if (requested && (MEAL_TYPES as readonly string[]).includes(requested)) {
      setMealType(requested as MealType);
    }
  }, []);
  const [grams, setGrams] = useState("100");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [quickAddFoodId, setQuickAddFoodId] = useState<string | null>(null);
  const [cookingFactor, setCookingFactor] = useState<number | null>(null);
  const [weighedAs, setWeighedAs] = useState<"raw" | "cooked">("raw");

  const [favorites, setFavorites] = useState<Favorite[]>([]);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editGrams, setEditGrams] = useState("");
  const [editMealType, setEditMealType] = useState<MealType>("lunch");
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const [copyFrom, setCopyFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return localDateIso(d);
  });
  const [copying, setCopying] = useState(false);
  const [copyMsg, setCopyMsg] = useState<string | null>(null);

  const [smartText, setSmartText] = useState("");
  const [smartConsent, setSmartConsent] = useState(false);
  const [smartRequesting, setSmartRequesting] = useState(false);
  const [smartError, setSmartError] = useState<string | null>(null);
  const [smartWarning, setSmartWarning] = useState<string | null>(null);
  const [smartQuestion, setSmartQuestion] = useState<string | null>(null);
  const [smartMissing, setSmartMissing] = useState<string[]>([]);
  const [smartReviewItems, setSmartReviewItems] = useState<SmartLogReviewItem[]>([]);
  const [smartConfirmingIndex, setSmartConfirmingIndex] = useState<number | null>(null);
  const smartPollCountRef = useRef(0);
  const smartElapsed = useElapsedSeconds(smartRequesting);
  const { quota: smartQuota, reload: reloadSmartQuota } = useAiQuota("smart_log");

  useEffect(() => {
    void loadDay(logDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logDate]);

  useEffect(() => {
    const onFlushed = () => void loadDay(logDate);
    window.addEventListener(QUEUE_FLUSHED_EVENT, onFlushed);
    return () => window.removeEventListener(QUEUE_FLUSHED_EVENT, onFlushed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logDate]);

  useEffect(() => {
    // Los favoritos son el atajo para registrar sin conexión: se guardan en el dispositivo
    // para poder ofrecerlos aunque no haya red.
    const key = `myfood:favorites:${userId}`;
    apiFetch<{ items: Favorite[] }>("/api/favorites?limit=8")
      .then((res) => {
        setFavorites(res.items);
        try {
          localStorage.setItem(key, JSON.stringify(res.items));
        } catch {
          // sin almacenamiento local: solo se pierde el modo sin conexión
        }
      })
      .catch(() => {
        try {
          const saved = localStorage.getItem(key);
          if (saved) setFavorites(JSON.parse(saved) as Favorite[]);
        } catch {
          // los favoritos son un atajo opcional
        }
      });
  }, [userId]);

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

  useEffect(() => {
    // El factor de cocción solo está en la ficha del alimento: se pide al elegirlo.
    setCookingFactor(null);
    setWeighedAs("raw");
    if (!selectedFood) return;
    let cancelled = false;
    apiFetch<{ cooking_yield_factor: number | null }>(`/api/foods/${selectedFood.id}`)
      .then((f) => !cancelled && setCookingFactor(f.cooking_yield_factor ?? null))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selectedFood]);

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
    setQueuedNote(null);
    try {
      const outcome = await submitOrQueue({
        userId: userId ?? "",
        kind: "food",
        label: `${selectedFood.name_es} — ${Number(grams)} g (${MEAL_TYPE_LABELS[mealType]}, ${logDate})`,
        payload: {
          log_date: logDate,
          meal_type: mealType,
          food_id: selectedFood.id,
          grams: Number(grams),
          weighed_as: cookingFactor ? weighedAs : "raw",
        },
      });
      if (outcome.queued) {
        setQueuedNote(
          "Sin conexión: guardado en este dispositivo. Se registrará solo al volver la red.",
        );
      }
      if (quickAddFoodId === selectedFood.id && !outcome.queued) {
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

  async function onCopyDay() {
    if (copyFrom === logDate) {
      setCopyMsg("Elige un día distinto del que estás viendo.");
      return;
    }
    const existing = day?.food.length ?? 0;
    if (
      existing > 0 &&
      !window.confirm(
        `El ${logDate} ya tiene ${existing} registro(s). Lo copiado se añadirá además de lo que hay. ¿Continuar?`,
      )
    ) {
      return;
    }
    setCopying(true);
    setCopyMsg(null);
    try {
      const copied = await apiFetch<LogFoodEntry[]>(
        `/api/log/copy-day?from_date=${copyFrom}&to_date=${logDate}`,
        { method: "POST" },
      );
      setCopyMsg(
        copied.length === 0
          ? `El ${copyFrom} no tiene registros que copiar.`
          : `Copiados ${copied.length} registro(s) del ${copyFrom}.`,
      );
      await loadDay(logDate);
    } catch (err) {
      setCopyMsg(errorMessage(err));
    } finally {
      setCopying(false);
    }
  }

  function startEdit(entry: LogFoodEntry) {
    setEditingId(entry.id);
    setEditGrams(String(entry.weighed_as === "cooked" && entry.entered_grams ? entry.entered_grams : entry.grams));
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

  /** Espera a que el worker termine de interpretar el texto. Devuelve una promesa que solo
   * se resuelve cuando la sesión deja de estar `running` — antes esta función se resolvía
   * tras el PRIMER sondeo (los siguientes iban por `setTimeout`), así que el botón volvía a
   * habilitarse al instante mientras seguía trabajando: justo lo que invita a reenviar. */
  function pollSmartLogSession(sessionId: string): Promise<void> {
    smartPollCountRef.current = 0;
    return new Promise<void>((resolve) => {
      const tick = async () => {
        smartPollCountRef.current += 1;
        let session: AiSession;
        try {
          session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
        } catch (err) {
          setSmartError(errorMessage(err));
          resolve();
          return;
        }
        if (session.status === "running") {
          if (smartPollCountRef.current >= SMART_LOG_MAX_POLL_ATTEMPTS) {
            setSmartError(
              "La interpretación está tardando más de lo esperado. Vuelve a entrar en un " +
                "momento: si termina, la verás aquí sin gastar otra petición.",
            );
            resolve();
            return;
          }
          setTimeout(() => void tick(), SMART_LOG_POLL_INTERVAL_MS);
          return;
        }
        if (session.status !== "succeeded") {
          const detail = session.validation_errors?.[0]?.message;
          setSmartError(detail ?? "No se ha podido interpretar el texto.");
          resolve();
          return;
        }
        const payload = session.response_payload as SmartLogResult | null;
        const items = payload?.items ?? [];
        setSmartReviewItems(
          items.map((item) => ({
            ...item,
            gramsInput: String(item.grams),
            mealType: mealType,
          })),
        );
        setSmartWarning(items.length === 0 ? (payload?.warning ?? "NO_MATCH") : null);
        setSmartQuestion(payload?.pregunta ?? null);
        setSmartMissing(payload?.no_encontrados ?? []);
        resolve();
      };
      void tick();
    });
  }

  async function onSmartLogSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Segunda barrera además de `disabled`: el Enter del teclado móvil puede llegar
    // mientras el botón ya está deshabilitado, y cada envío gasta una petición del día.
    if (smartRequesting || !smartText.trim()) return;
    setSmartRequesting(true);
    setSmartError(null);
    setSmartWarning(null);
    setSmartQuestion(null);
    setSmartMissing([]);
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
        body: JSON.stringify({ text: smartText.trim() }),
      });
      await pollSmartLogSession(session.id);
    } catch (err) {
      setSmartError(
        err instanceof ApiError && err.status === 429
          ? `${err.message} Se reinician a las 00:00.`
          : errorMessage(err),
      );
    } finally {
      setSmartRequesting(false);
      reloadSmartQuota();
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

  /** Cambia el alimento por una de las alternativas que el modelo consideró, sin volver a
   * escribir la frase ni gastar otra petición. Los gramos se conservan: la cantidad la dijo el
   * usuario, no depende de qué alimento sea. */
  function swapSmartReviewItem(index: number, alternative: SmartLogAlternative) {
    setSmartReviewItems((prev) =>
      prev.map((item, i) => {
        if (i !== index) return item;
        const rest = (item.alternativas ?? []).filter((a) => a.food_id !== alternative.food_id);
        return {
          ...item,
          food_id: alternative.food_id,
          name_es: alternative.name_es,
          motivo: undefined,
          alternativas: [{ food_id: item.food_id, name_es: item.name_es }, ...rest].slice(0, 2),
        };
      }),
    );
  }

  async function confirmSmartReviewItem(index: number) {
    const item = smartReviewItems[index];
    setSmartConfirmingIndex(index);
    setSmartError(null);
    try {
      await submitOrQueue({
        userId: userId ?? "",
        kind: "food",
        label: `${item.name_es} — ${Number(item.gramsInput)} g (${MEAL_TYPE_LABELS[item.mealType]}, ${logDate})`,
        payload: {
          log_date: logDate,
          meal_type: item.mealType,
          food_id: item.food_id,
          grams: Number(item.gramsInput),
        },
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
    <main className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-extrabold tracking-tight">Diario</h1>
        <DayPager date={logDate} onChange={setLogDate} />
      </div>

      <section aria-label="Comidas del día" className="flex flex-col gap-4">
        {loading && <Skeleton lines={3} />}
        {error && <ErrorState message={error} onRetry={() => void loadDay(logDate)} />}
        {day && (
          <>
            <div className="grid grid-cols-4 gap-2 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-center shadow-[var(--shadow-card)]">
              {[
                { label: "Kcal", value: day.totals.kcal, unit: "", color: "var(--color-primary)" },
                { label: "Proteína", value: day.totals.protein_g, unit: " g", color: "var(--color-protein)" },
                { label: "Carbos", value: day.totals.carbs_g, unit: " g", color: "var(--color-carbs)" },
                { label: "Grasa", value: day.totals.fat_g, unit: " g", color: "var(--color-fat)" },
              ].map((cell) => (
                <div key={cell.label}>
                  <p className="flex items-center justify-center gap-1 text-xs text-[var(--color-muted)]">
                    <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: cell.color }} />
                    {cell.label}
                  </p>
                  <p className="text-lg font-extrabold tracking-tight">
                    {Math.round(Number(cell.value) * 10) / 10}
                    {cell.unit}
                  </p>
                </div>
              ))}
            </div>
            {day.food.length === 0 ? (
              <EmptyState message="Todavía no hay entradas para este día." actionLabel="Escanear un producto" actionHref="/scan" />
            ) : (
              <div className="flex flex-col gap-3">
                {groupByMeal(day.food).map((group) => (
                  <div
                    key={group.mealType}
                    className="overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)]"
                  >
                    <div className="flex items-center justify-between gap-3 px-4 py-3">
                      <h2 className="text-[15px] font-bold">{MEAL_TYPE_LABELS[group.mealType]}</h2>
                      <span className="text-xs font-semibold text-[var(--color-muted)]">
                        {Math.round(group.entries.reduce((sum, e) => sum + Number(e.kcal), 0))} kcal
                      </span>
                    </div>
                    <ul className="divide-y divide-[var(--color-border)] border-t border-[var(--color-border)] px-4">
                      {group.entries.map((entry) => (
                        <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                    {editingId === entry.id ? (
                      <div className="flex flex-wrap items-end gap-3">
                        <span className="text-sm font-medium">
                          {entry.recipe_name ??
                            ((entry.food_id && foodNames[entry.food_id]) || "Alimento")}
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
                        {entry.food_id && (
                          <input
                            type="number"
                            min={1}
                            max={5000}
                            className={inputClass}
                            value={editGrams}
                            onChange={(e) => setEditGrams(e.target.value)}
                            aria-label={
                              entry.weighed_as === "cooked" ? "Gramos (peso cocinado)" : "Gramos"
                            }
                          />
                        )}
                        <button
                          type="button"
                          onClick={() => onSaveEdit(entry.id)}
                          disabled={rowBusy === entry.id}
                          className="rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
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
                          <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                            {entry.recipe_name ??
                              entry.food_name ??
                              ((entry.food_id && foodNames[entry.food_id]) || "Alimento")}
                            {entry.entry_source === "ai_estimate" && (
                              <span
                                title="Este alimento no está en el catálogo: sus valores los estimó Claude."
                                className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-900 dark:bg-amber-950 dark:text-amber-200"
                              >
                                <Sparkles size={9} aria-hidden="true" /> estimado
                              </span>
                            )}
                          </p>
                          <p className="text-xs text-neutral-500">
                                                        {entry.weighed_as === "cooked" && entry.entered_grams
                              ? `${entry.entered_grams} g cocinado (≈${entry.grams} g crudo)`
                              : `${entry.grams} g`}{" "}
                            · {entry.kcal} kcal
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
                            className="text-red-600 dark:text-red-400 underline disabled:opacity-60"
                          >
                            Eliminar
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
            {rowError && <p className="text-sm text-red-600 dark:text-red-400">{rowError}</p>}
            <MicronutrientsPanel date={logDate} />
          </>
        )}
      </section>

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

      <section id="registrar" className="scroll-mt-20">
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
            {cookingFactor ? (
              <fieldset className="flex flex-col gap-1 text-sm">
                <legend className="mb-1">¿Lo pesaste crudo o ya cocinado?</legend>
                <div className="flex gap-3">
                  {(["raw", "cooked"] as const).map((v) => (
                    <label key={v} className="flex items-center gap-1">
                      <input
                        type="radio"
                        name="log-weighed-as"
                        checked={weighedAs === v}
                        onChange={() => setWeighedAs(v)}
                      />
                      {v === "raw" ? "Crudo" : "Cocinado"}
                    </label>
                  ))}
                </div>
                {weighedAs === "cooked" && Number(grams) > 0 && (
                  <span className="text-xs text-neutral-500">
                    ≈ {Math.round(Number(grams) / cookingFactor)} g en crudo.
                  </span>
                )}
              </fieldset>
            ) : null}
            <button
              type="submit"
              disabled={adding}
              className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
            >
              {adding ? "Guardando…" : "Añadir"}
            </button>
          </form>
        )}
        {addError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{addError}</p>}
        {queuedNote && (
          <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">{queuedNote}</p>
        )}
      </section>

      <section id="natural" className="scroll-mt-20 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Registrar con lenguaje natural</h2>
          <QuotaBadge quota={smartQuota} />
        </div>
        <p className="mb-3 text-sm text-neutral-500">
          Escribe lo que has comido como se lo contarías a alguien: &quot;hoy he almorzado
          una porción de tortilla de patatas, otra de ensaladilla y 4 trozos de pan&quot;.
          Claude entiende las cantidades de casa (porción, plato, trozo, vaso…) y si el plato
          es casero o de paquete; los gramos y las calorías los pone el catálogo. Tú revisas y
          ajustas antes de confirmar.
        </p>
        <form onSubmit={onSmartLogSubmit} className="flex flex-wrap items-end gap-3">
          <input
            type="text"
            required
            placeholder="una porción de tortilla de patatas y 4 trozos de pan..."
            className={`${inputClass} min-w-[16rem] flex-1`}
            value={smartText}
            onChange={(e) => setSmartText(e.target.value)}
            disabled={smartRequesting}
          />
          <button
            type="submit"
            disabled={smartRequesting || smartQuota?.remaining === 0}
            className="inline-flex items-center gap-2 rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {smartRequesting && <ThinkingDots />}
            {smartRequesting ? "Interpretando…" : "Interpretar"}
          </button>
        </form>
        <label className="mt-2 flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={smartConsent}
            onChange={(e) => setSmartConsent(e.target.checked)}
            className="mt-0.5"
            disabled={smartRequesting}
          />
          Acepto que este texto (sin nombre ni datos identificativos) se envíe a Claude
          para interpretarlo.
        </label>

        {smartRequesting && (
          <div className="mt-3">
            <AiWaiting task="smart_log" elapsedSeconds={smartElapsed} />
          </div>
        )}
        {!smartRequesting && smartQuota?.remaining === 0 && (
          <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">
            Has gastado tus {smartQuota.limit} interpretaciones de hoy. Vuelven a las 00:00 —
            mientras tanto puedes registrar buscando el alimento aquí arriba.
          </p>
        )}
        {smartError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{smartError}</p>}
        {smartWarning && (
          <p className="mt-2 text-sm text-neutral-500">
            No se ha encontrado ningún alimento parecido en el catálogo para ese texto.
          </p>
        )}
        {smartQuestion && (
          <p className="mt-2 rounded-[var(--radius-control)] border border-amber-300 bg-amber-50 p-2 text-sm dark:border-amber-800 dark:bg-amber-950">
            <span className="font-medium">Para afinar: </span>
            {smartQuestion} Añádelo al texto y vuelve a interpretarlo, o ajusta los gramos a
            mano aquí abajo.
          </p>
        )}
        {smartMissing.length > 0 && (
          <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
            No está en el catálogo: <span className="font-medium">{smartMissing.join(", ")}</span>.{" "}
            <Link href="/chat" className="underline">
              Díselo al chat
            </Link>{" "}
            — ese sí sabe estimar un plato que no tenemos fichado.
          </p>
        )}

        {smartReviewItems.length > 0 && (
          <div className="mt-4 flex flex-col gap-3">
            {smartReviewItems.map((item, index) => (
              <div
                key={`${item.food_id}-${index}`}
                className="flex flex-wrap items-end gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3"
              >
                <div className="min-w-[12rem] flex-1">
                  <p className="text-sm font-medium">{item.name_es}</p>
                  <p className="text-xs text-neutral-500">
                    &quot;{item.approx_quantity_text}&quot;
                    {describeInterpretation(item) && <> · {describeInterpretation(item)}</>}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    {item.origen && item.origen !== "desconocido" && (
                      <span className="rounded-full bg-[var(--color-primary-soft)] px-2 py-0.5 text-[11px] font-semibold text-[var(--color-primary)]">
                        {ORIGIN_LABELS[item.origen]}
                      </span>
                    )}
                    {item.confianza === "baja" && (
                      <span
                        className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                        title="Revisa este con más cuidado"
                      >
                        poco seguro
                      </span>
                    )}
                  </div>
                  {item.motivo && (
                    <p className="mt-1 text-xs text-neutral-500">{item.motivo}</p>
                  )}
                  {(item.alternativas?.length ?? 0) > 0 && (
                    <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-neutral-500">
                      ¿No era ese?
                      {item.alternativas?.map((alt) => (
                        <button
                          key={alt.food_id}
                          type="button"
                          onClick={() => swapSmartReviewItem(index, alt)}
                          className="rounded-full border border-[var(--color-border-strong)] px-2 py-0.5 font-medium hover:bg-[var(--color-surface-2)]"
                        >
                          {alt.name_es}
                        </button>
                      ))}
                    </p>
                  )}
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
                  className="rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
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

      <section className="flex flex-wrap items-end gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm shadow-[var(--shadow-card)]">
        <label className="flex flex-col gap-1">
          Copiar los registros del día
          <input
            type="date"
            className={inputClass}
            value={copyFrom}
            onChange={(e) => setCopyFrom(e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => void onCopyDay()}
          disabled={copying}
          className="rounded-full border border-[var(--color-border-strong)] font-medium px-3 py-2 disabled:opacity-60"
        >
          {copying ? "Copiando…" : `Copiar al ${logDate}`}
        </button>
        {copyMsg && <span className="text-neutral-600 dark:text-neutral-400">{copyMsg}</span>}
      </section>
    </main>
  );
}
