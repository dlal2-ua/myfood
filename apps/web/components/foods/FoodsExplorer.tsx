"use client";

import { ChevronDown, ScanBarcode, Search, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { FacetSheet } from "@/components/foods/FacetSheet";
import { FoodRow, FoodTile } from "@/components/foods/FoodCard";
import { LogFoodSheet } from "@/components/foods/LogFoodSheet";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { apiFetch, errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import {
  FACET_TITLES,
  PAGE_SIZE,
  SORT_LABELS,
  activeChips,
  activeCount,
  emptyFilters,
  hasCriteria,
  toSearchQuery,
  toggleOption,
  type FacetKey,
  type FilterState,
  type SortKey,
} from "@/lib/foodFilters";
import { mealTypeForTime } from "@/lib/meals";
import type {
  FoodFacets,
  FoodSearchItem,
  FoodSearchResponse,
  SuggestionSection,
  SuggestionsResponse,
} from "@/lib/types";

const FACET_KEYS: FacetKey[] = ["supermarket", "food_type", "nutrition"];
const DEBOUNCE_MS = 300;

function Suggestions({
  sections,
  onAdd,
}: {
  sections: SuggestionSection[];
  onAdd: (item: FoodSearchItem) => void;
}) {
  return (
    <div className="flex flex-col gap-7">
      {sections.map((section) => (
        <section key={section.key} aria-labelledby={`sug-${section.key}`}>
          <div className="mb-3">
            <h2 id={`sug-${section.key}`} className="text-lg font-extrabold tracking-tight">
              {section.title}
            </h2>
            {section.subtitle && <p className="text-xs text-[var(--color-muted)]">{section.subtitle}</p>}
          </div>
          <ul className="scroll-row -mx-4 flex gap-3 overflow-x-auto px-4 pb-2 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
            {section.items.map((item) => (
              <li key={item.id} className="flex">
                <FoodTile item={item} onAdd={() => onAdd(item)} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Pantalla «Alimentos»: buscador con filtros por supermercado, tipo de alimento y nutrición.
 * Sin texto ni filtros enseña sugerencias (favoritos, habituales, lo que falta hoy, básicos para
 * la comida que toca, despensa); con ellos, los resultados con cuántos alimentos deja cada opción. */
export function FoodsExplorer() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  const [sort, setSort] = useState<SortKey>("relevance");
  const [openFacet, setOpenFacet] = useState<FacetKey | null>(null);

  const [items, setItems] = useState<FoodSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<FoodFacets | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<SuggestionSection[] | null>(null);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);

  const [adding, setAdding] = useState<FoodSearchItem | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const criteria = hasCriteria(debounced, filters);
  const requestId = useRef(0);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  const loadSuggestions = useCallback(async () => {
    setSuggestionsError(null);
    try {
      const params = new URLSearchParams({ meal_type: mealTypeForTime(), date: localDateIso() });
      const res = await apiFetch<SuggestionsResponse>(`/api/foods/suggestions?${params}`);
      setSuggestions(res.sections);
    } catch (err) {
      setSuggestionsError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void loadSuggestions();
  }, [loadSuggestions]);

  // Busca al cambiar el texto, los filtros o el orden. Sin nada que buscar solo pide las opciones
  // de los filtros (una fila) para poder enseñarlas con su recuento.
  useEffect(() => {
    const id = ++requestId.current;
    const searching = criteria;
    setLoading(true);
    setError(null);
    const qs = toSearchQuery({ query: debounced, filters, sort, facets: true, limit: searching ? PAGE_SIZE : 1 });
    apiFetch<FoodSearchResponse>(`/api/foods/search?${qs}`)
      .then((res) => {
        if (id !== requestId.current) return; // llegó tarde: ya hay otra búsqueda en marcha
        setFacets(res.facets ?? null);
        if (searching) {
          setItems(res.items);
          setTotal(res.total);
        } else {
          setItems([]);
          setTotal(0);
        }
      })
      .catch((err) => {
        if (id === requestId.current) setError(errorMessage(err));
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false);
      });
  }, [debounced, filters, sort, criteria, reloadTick]);

  async function loadMore() {
    const id = requestId.current;
    setLoadingMore(true);
    try {
      const qs = toSearchQuery({ query: debounced, filters, sort, offset: items.length });
      const res = await apiFetch<FoodSearchResponse>(`/api/foods/search?${qs}`);
      if (id !== requestId.current) return;
      setItems((current) => [...current, ...res.items.filter((i) => !current.some((c) => c.id === i.id))]);
      setTotal(res.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  }

  const chips = activeChips(filters, facets);
  const filterCount = activeCount(filters);
  const clearAll = () => setFilters(emptyFilters());

  return (
    <main className="flex flex-col gap-4">
      <h1 className="text-3xl font-extrabold tracking-tight">Alimentos</h1>

      <label className="relative block">
        <span className="sr-only">Buscar un alimento</span>
        <Search
          size={18}
          aria-hidden="true"
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[var(--color-muted)]"
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Busca un alimento o una marca…"
          className="h-12 w-full rounded-full pl-11 pr-11 text-[15px] shadow-[var(--shadow-card)]"
        />
        {query ? (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Borrar la búsqueda"
            className="absolute right-2 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-[var(--color-muted)] hover:bg-[var(--color-surface-2)]"
          >
            <X size={18} aria-hidden="true" />
          </button>
        ) : (
          <Link
            href="/scan"
            aria-label="Escanear un código de barras"
            title="Escanear un código de barras"
            className="absolute right-2 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-[var(--color-muted)] hover:bg-[var(--color-surface-2)]"
          >
            <ScanBarcode size={18} aria-hidden="true" />
          </Link>
        )}
      </label>

      <div role="group" aria-label="Filtros" className="scroll-row -mx-4 flex gap-2 overflow-x-auto px-4 py-0.5 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
        {FACET_KEYS.map((key) => {
          const count = activeCount(filters, key);
          return (
            <button
              key={key}
              type="button"
              onClick={() => setOpenFacet(key)}
              aria-haspopup="dialog"
              className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-full border px-4 text-sm font-semibold transition-colors ${
                count > 0
                  ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)] text-[var(--color-primary)]"
                  : "border-[var(--color-border-strong)] bg-[var(--color-surface)] hover:border-[var(--color-primary)]"
              }`}
            >
              {key === "supermarket" && <SlidersHorizontal size={15} aria-hidden="true" />}
              {FACET_TITLES[key]}
              {count > 0 && <span className="rounded-full bg-[var(--color-primary)] px-1.5 text-xs text-[var(--color-on-primary)]">{count}</span>}
              <ChevronDown size={15} aria-hidden="true" />
            </button>
          );
        })}
      </div>

      {chips.length > 0 && (
        <ul aria-label="Filtros elegidos" className="flex flex-wrap items-center gap-2">
          {chips.map((chip) => (
            <li key={`${chip.key}-${chip.code}`}>
              <button
                type="button"
                onClick={() => setFilters((f) => toggleOption(f, chip.key, chip.code))}
                aria-label={`Quitar el filtro ${chip.label}`}
                className="inline-flex min-h-8 items-center gap-1 rounded-full bg-[var(--color-primary-soft)] py-1 pl-3 pr-2 text-xs font-bold text-[var(--color-primary)]"
              >
                {chip.label} <X size={14} aria-hidden="true" />
              </button>
            </li>
          ))}
          <li>
            <button type="button" onClick={clearAll} className="min-h-8 px-2 text-xs font-semibold text-[var(--color-muted)] underline">
              Limpiar filtros
            </button>
          </li>
        </ul>
      )}

      {criteria ? (
        <section aria-label="Resultados" className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <p role="status" aria-live="polite" className="text-sm text-[var(--color-muted)]">
              {loading ? "Buscando…" : `${total} ${total === 1 ? "resultado" : "resultados"}`}
            </p>
            <label className="flex items-center gap-2 text-xs font-semibold text-[var(--color-muted)]">
              Ordenar
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortKey)}
                className="min-h-9 rounded-full px-3 text-xs font-semibold"
              >
                {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                  <option key={key} value={key}>
                    {SORT_LABELS[key]}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error ? (
            <ErrorState message={error} onRetry={() => setReloadTick((n) => n + 1)} />
          ) : loading && items.length === 0 ? (
            <Skeleton lines={6} />
          ) : items.length === 0 ? (
            <EmptyState
              message="No hay alimentos con esa búsqueda y esos filtros."
              actionLabel={filterCount > 0 ? "Quitar los filtros" : undefined}
              onAction={filterCount > 0 ? clearAll : undefined}
            />
          ) : (
            <>
              <ul className="flex flex-col gap-2.5">
                {items.map((item) => (
                  <li key={item.id}>
                    <FoodRow item={item} onAdd={() => setAdding(item)} />
                  </li>
                ))}
              </ul>
              {items.length < total && (
                <button
                  type="button"
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                  className="min-h-12 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold disabled:opacity-60"
                >
                  {loadingMore ? "Cargando…" : "Cargar más"}
                </button>
              )}
            </>
          )}
          <p className="text-center text-xs text-[var(--color-muted)]">
            ¿No lo encuentras? <Link href="/scan" className="font-semibold underline">Escanéalo o añádelo a mano</Link>.
          </p>
        </section>
      ) : suggestionsError ? (
        <ErrorState message={suggestionsError} onRetry={() => void loadSuggestions()} />
      ) : suggestions === null ? (
        <Skeleton lines={6} />
      ) : suggestions.length === 0 ? (
        <EmptyState message="Escribe el nombre de un alimento o elige un filtro para empezar." />
      ) : (
        <Suggestions sections={suggestions} onAdd={setAdding} />
      )}

      <LogFoodSheet
        foodId={adding?.id ?? null}
        foodName={adding?.name_es}
        onClose={() => setAdding(null)}
        onLogged={() => void loadSuggestions()}
      />

      <FacetSheet
        facetKey={openFacet}
        options={openFacet ? (facets?.[openFacet] ?? []) : []}
        selected={openFacet ? filters[openFacet] : []}
        total={criteria ? total : null}
        loading={loading}
        onToggle={(code) => openFacet && setFilters((f) => toggleOption(f, openFacet, code))}
        onClear={() => openFacet && setFilters((f) => ({ ...f, [openFacet]: [] }))}
        onClose={() => setOpenFacet(null)}
      />
    </main>
  );
}
