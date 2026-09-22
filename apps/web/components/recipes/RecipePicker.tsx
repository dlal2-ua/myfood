"use client";

import { ChefHat, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { CatalogPage, CatalogRecipe, RecipeSummary } from "@/lib/types";

const DEBOUNCE_MS = 300;
const MAX_RESULTS = 8;

/** Elegir una receta para una comida del plan: las tuyas y las del recetario compartido.
 *
 * El recetario tiene cientos de platos, así que no cabe en un desplegable: las propias van en
 * la lista (suelen ser pocas) y el recetario se busca escribiendo. */
export function RecipePicker({
  own,
  value,
  onChange,
  disabled,
}: {
  own: RecipeSummary[];
  value: string;
  onChange: (recipeId: string, name: string) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [results, setResults] = useState<CatalogRecipe[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    if (!debounced.trim()) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    apiFetch<CatalogPage>(
      `/api/recipes/catalog?q=${encodeURIComponent(debounced.trim())}&limit=${MAX_RESULTS}`,
    )
      .then((page) => !cancelled && setResults(page.items))
      .catch(() => !cancelled && setResults([]))
      .finally(() => !cancelled && setSearching(false));
    return () => {
      cancelled = true;
    };
  }, [debounced]);

  return (
    <div className="flex min-w-[14rem] flex-1 flex-col gap-1.5">
      {own.length > 0 && (
        <select
          value={own.some((r) => r.id === value) ? value : ""}
          disabled={disabled}
          onChange={(e) => {
            const recipe = own.find((r) => r.id === e.target.value);
            if (recipe) onChange(recipe.id, recipe.name);
          }}
          className="min-h-9 rounded-[var(--radius-control)] px-2 text-xs"
        >
          <option value="">Una de tus recetas…</option>
          {own.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
      )}

      <label className="relative block">
        <span className="sr-only">Buscar en el recetario</span>
        <Search
          size={13}
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-muted)]"
        />
        <input
          type="search"
          value={query}
          disabled={disabled}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="…o busca en el recetario"
          className="min-h-9 w-full rounded-[var(--radius-control)] pl-7 pr-2 text-xs"
        />
      </label>

      {debounced.trim() && (
        <ul className="max-h-44 overflow-y-auto rounded-[var(--radius-control)] border border-[var(--color-border)]">
          {searching && results.length === 0 && (
            <li className="px-2 py-1.5 text-xs text-[var(--color-muted)]">Buscando…</li>
          )}
          {!searching && results.length === 0 && (
            <li className="px-2 py-1.5 text-xs text-[var(--color-muted)]">
              Ningún plato con ese nombre.
            </li>
          )}
          {results.map((recipe) => (
            <li key={recipe.id}>
              <button
                type="button"
                onClick={() => {
                  onChange(recipe.id, recipe.name);
                  setQuery("");
                }}
                className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs hover:bg-[var(--color-surface-2)] ${
                  value === recipe.id ? "bg-[var(--color-primary-soft)]" : ""
                }`}
              >
                <ChefHat size={12} aria-hidden="true" className="shrink-0 text-[var(--color-muted)]" />
                <span className="min-w-0 flex-1 truncate">{recipe.name}</span>
                <span className="shrink-0 text-[var(--color-muted)]">
                  {Math.round(recipe.kcal_per_serving)} kcal
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
