import type { FacetOption, FoodFacets } from "@/lib/types";

/** Los tres filtros del catálogo. Dentro de supermercado y tipo de alimento las opciones se suman
 * (Lidl o Aldi); las de nutrición se exigen todas (alto en proteína y bajo en grasa). */
export type FacetKey = "supermarket" | "food_type" | "nutrition";

export type FilterState = Record<FacetKey, string[]>;
export type SortKey = "relevance" | "kcal_asc" | "protein_desc";

export const FACET_TITLES: Record<FacetKey, string> = {
  supermarket: "Supermercado",
  food_type: "Tipo de alimento",
  nutrition: "Nutrición",
};

export const FACET_HINTS: Record<FacetKey, string> = {
  supermarket: "Productos de las marcas de cada cadena. Puedes elegir varias.",
  food_type: "Puedes elegir varios tipos.",
  nutrition: "Por 100 g. Se cumplen todas las que elijas.",
};

export const SORT_LABELS: Record<SortKey, string> = {
  relevance: "Relevancia",
  kcal_asc: "Menos calorías",
  protein_desc: "Más proteína",
};

export const PAGE_SIZE = 20;
export const MIN_QUERY_LENGTH = 2;

export const emptyFilters = (): FilterState => ({ supermarket: [], food_type: [], nutrition: [] });

export function activeCount(filters: FilterState, key?: FacetKey): number {
  if (key) return filters[key].length;
  return filters.supermarket.length + filters.food_type.length + filters.nutrition.length;
}

export function toggleOption(filters: FilterState, key: FacetKey, code: string): FilterState {
  const current = filters[key];
  const next = current.includes(code) ? current.filter((c) => c !== code) : [...current, code];
  return { ...filters, [key]: next };
}

/** ¿Hay algo con lo que buscar? Si no, la pantalla enseña las sugerencias. */
export function hasCriteria(query: string, filters: FilterState): boolean {
  return query.trim().length >= MIN_QUERY_LENGTH || activeCount(filters) > 0;
}

export interface SearchParams {
  query: string;
  filters: FilterState;
  sort: SortKey;
  offset?: number;
  limit?: number;
  facets?: boolean;
}

/** Cadena de consulta de `/api/foods/search`. Un texto de un solo carácter no se manda: es ruido. */
export function toSearchQuery({ query, filters, sort, offset = 0, limit = PAGE_SIZE, facets = false }: SearchParams): string {
  const params = new URLSearchParams();
  const q = query.trim();
  if (q.length >= MIN_QUERY_LENGTH) params.set("q", q);
  for (const code of filters.supermarket) params.append("supermarket", code);
  for (const code of filters.food_type) params.append("food_type", code);
  for (const code of filters.nutrition) params.append("nutrition", code);
  if (sort !== "relevance") params.set("sort", sort);
  if (facets) params.set("facets", "true");
  params.set("limit", String(limit));
  if (offset > 0) params.set("offset", String(offset));
  return params.toString();
}

export interface ActiveChip {
  key: FacetKey;
  code: string;
  label: string;
}

/** Chips de los filtros elegidos, con el nombre que se muestra al usuario. */
export function activeChips(filters: FilterState, facets: FoodFacets | null): ActiveChip[] {
  const chips: ActiveChip[] = [];
  for (const key of ["supermarket", "food_type", "nutrition"] as const) {
    const options: FacetOption[] = facets?.[key] ?? [];
    for (const code of filters[key]) {
      chips.push({ key, code, label: options.find((o) => o.code === code)?.label ?? code });
    }
  }
  return chips;
}

/** Opciones que se enseñan en una hoja de filtro: las que dejan algún alimento, más las ya
 * elegidas (para poder quitarlas). En nutrición se enseñan todas, en su orden. */
export function visibleOptions(key: FacetKey, options: FacetOption[], selected: string[]): FacetOption[] {
  if (key === "nutrition") return options;
  return options.filter((o) => o.count > 0 || selected.includes(o.code));
}

/** La búsqueda entera en la barra de direcciones: texto, filtros y orden.
 *
 * Existe para que abrir un alimento y volver no pierda lo que estabas mirando. Antes el
 * estado vivía solo en React y, al volver, el componente se montaba de cero: los filtros
 * desaparecían y había que elegirlos otra vez. */
export function toUrlParams(query: string, filters: FilterState, sort: SortKey): string {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  for (const key of Object.keys(filters) as FacetKey[]) {
    if (filters[key].length > 0) params.set(key, filters[key].join(","));
  }
  if (sort !== "relevance") params.set("sort", sort);
  return params.toString();
}

export interface UrlState {
  query: string;
  filters: FilterState;
  sort: SortKey;
}

export function fromUrlParams(search: string): UrlState {
  const params = new URLSearchParams(search);
  const filters = emptyFilters();
  for (const key of Object.keys(filters) as FacetKey[]) {
    const raw = params.get(key);
    if (raw) filters[key] = raw.split(",").filter(Boolean);
  }
  const sort = params.get("sort");
  return {
    query: params.get("q") ?? "",
    filters,
    sort: sort === "kcal_asc" || sort === "protein_desc" ? sort : "relevance",
  };
}
