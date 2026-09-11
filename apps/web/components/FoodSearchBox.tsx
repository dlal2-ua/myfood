"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { FoodSearchItem, FoodSearchResponse } from "@/lib/types";

export function FoodSearchBox({ onSelect }: { onSelect: (item: FoodSearchItem) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<FoodSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setError(null);
      return;
    }
    const handle = setTimeout(() => {
      setLoading(true);
      setError(null);
      apiFetch<FoodSearchResponse>(`/api/foods/search?q=${encodeURIComponent(q)}&limit=15`)
        .then((res) => setResults(res.items))
        .catch((err) => setError(errorMessage(err)))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="flex flex-col gap-2">
      <input
        type="search"
        placeholder="Busca un alimento (mín. 2 letras)…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900"
      />
      {loading && <p className="text-xs text-neutral-500">Buscando…</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
      {results.length > 0 && (
        <ul className="divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
          {results.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-neutral-100 dark:hover:bg-neutral-900"
              >
                <span>
                  {item.name_es}
                  {item.brand && <span className="text-neutral-500"> · {item.brand}</span>}
                </span>
                <span className="whitespace-nowrap text-neutral-500">
                  {item.kcal_100g != null ? `${item.kcal_100g} kcal/100g` : "—"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
