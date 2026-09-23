"use client";

import { BookmarkPlus, ChefHat, Search, Users, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { apiFetch, errorMessage } from "@/lib/api";
import type { CatalogPage, CatalogRecipe, Recipe } from "@/lib/types";

const DEBOUNCE_MS = 300;
const PAGE_SIZE = 24;

function n(value: number): string {
  return String(Math.round(value * 10) / 10).replace(".", ",");
}

/** Los filtros del recetario. Van como pastillas y no como desplegable porque son pocos y
 * se eligen de un vistazo, igual que en «Alimentos». */
function Chips({
  label,
  options,
  selected,
  onSelect,
}: {
  label: string;
  options: string[];
  selected: string | null;
  onSelect: (value: string | null) => void;
}) {
  if (options.length === 0) return null;
  return (
    <div role="group" aria-label={label} className="scroll-row -mx-4 flex gap-2 overflow-x-auto px-4 py-0.5 md:mx-0 md:flex-wrap md:overflow-visible md:px-0">
      {options.map((option) => {
        const active = selected === option;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(active ? null : option)}
            className={`min-h-9 shrink-0 rounded-full border px-3.5 text-sm font-semibold transition-colors ${
              active
                ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)] text-[var(--color-primary)]"
                : "border-[var(--color-border-strong)] bg-[var(--color-surface)] hover:border-[var(--color-primary)]"
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

function RecipeCard({ recipe, onOpen }: { recipe: CatalogRecipe; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-col overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] text-left shadow-[var(--shadow-card)] transition-colors hover:border-[var(--color-primary)]"
      >
        {recipe.image_url ? (
          /* eslint-disable-next-line @next/next/no-img-element -- foto remota de la fuente */
          <img
            src={recipe.image_url}
            alt=""
            loading="lazy"
            className="h-36 w-full object-cover"
          />
        ) : (
          <span className="grid h-36 w-full place-items-center bg-[var(--color-surface-2)] text-[var(--color-muted)]">
            <ChefHat size={28} aria-hidden="true" />
          </span>
        )}
        <span className="flex flex-1 flex-col gap-1 p-3">
          <span className="line-clamp-2 text-[15px] font-bold leading-snug">{recipe.name}</span>
          <span className="flex flex-wrap items-center gap-x-2 text-xs text-[var(--color-muted)]">
            {recipe.cuisine && <span>{recipe.cuisine}</span>}
            {recipe.category && <span>· {recipe.category}</span>}
          </span>
          <span className="mt-0.5 text-sm">
            <b>{Math.round(recipe.kcal_per_serving)} kcal</b>
            <span className="text-xs text-[var(--color-muted)]"> por ración</span>
          </span>
          <span className="text-xs text-[var(--color-muted)]">
            P {n(recipe.protein_g_per_serving)} · C {n(recipe.carbs_g_per_serving)} · G{" "}
            {n(recipe.fat_g_per_serving)}
          </span>
        </span>
      </button>
    </li>
  );
}

/** Ficha completa de una receta del catálogo: ingredientes con sus gramos, los pasos y lo que
 * aporta por ración. Desde aquí se guarda entre las tuyas para poder ajustarla. */
function RecipeSheet({
  recipeId,
  fallbackName,
  onClose,
}: {
  recipeId: string | null;
  fallbackName?: string;
  onClose: () => void;
}) {
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!recipeId) return;
    setRecipe(null);
    setError(null);
    setSaved(false);
    let cancelled = false;
    apiFetch<Recipe>(`/api/recipes/${recipeId}`)
      .then((r) => !cancelled && setRecipe(r))
      .catch((err) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [recipeId]);

  async function save() {
    if (!recipeId) return;
    setSaving(true);
    try {
      await apiFetch(`/api/recipes/${recipeId}/copy`, { method: "POST" });
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <BottomSheet
      open={recipeId !== null}
      onClose={onClose}
      title={recipe?.name ?? fallbackName ?? "Receta"}
    >
      {error && <ErrorState message={error} />}
      {!recipe && !error && <Skeleton lines={6} />}
      {recipe && (
        <div className="flex flex-col gap-4">
          {recipe.image_url && (
            /* eslint-disable-next-line @next/next/no-img-element -- foto remota de la fuente */
            <img
              src={recipe.image_url}
              alt=""
              className="h-44 w-full rounded-[var(--radius-card)] object-cover"
            />
          )}

          <div className="rounded-[var(--radius-card)] bg-[var(--color-surface-2)] p-3">
            <p className="flex items-baseline justify-between gap-3">
              <span className="text-sm font-bold">Por ración</span>
              <span className="text-2xl font-extrabold tracking-tight">
                {Math.round(recipe.totals_per_serving.kcal)} kcal
              </span>
            </p>
            <ul className="mt-1 flex flex-wrap gap-x-4 text-xs text-[var(--color-muted)]">
              <li>Proteína <b>{n(recipe.totals_per_serving.protein_g)} g</b></li>
              <li>Carbos <b>{n(recipe.totals_per_serving.carbs_g)} g</b></li>
              <li>Grasa <b>{n(recipe.totals_per_serving.fat_g)} g</b></li>
            </ul>
            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-[var(--color-muted)]">
              <Users size={12} aria-hidden="true" /> {recipe.servings} raciones · calculado
              sumando sus ingredientes
            </p>
          </div>

          <div>
            <h3 className="mb-1.5 text-sm font-bold">Ingredientes</h3>
            <ul className="flex flex-col gap-1 text-sm">
              {recipe.ingredients.map((ingredient) => (
                <li key={ingredient.id} className="flex justify-between gap-3">
                  <span className="min-w-0 flex-1">{ingredient.name_es}</span>
                  <span className="shrink-0 text-[var(--color-muted)]">
                    {n(ingredient.grams)} g
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {recipe.instructions && (
            <div>
              <h3 className="mb-1.5 text-sm font-bold">Cómo se hace</h3>
              <p className="whitespace-pre-line text-sm leading-relaxed text-[var(--color-muted)]">
                {recipe.instructions}
              </p>
            </div>
          )}

          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || saved}
            className="inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-[var(--color-primary)] text-sm font-bold text-[var(--color-on-primary)] disabled:opacity-60"
          >
            <BookmarkPlus size={16} aria-hidden="true" />
            {saved ? "Guardada en tus recetas" : saving ? "Guardando…" : "Guardar en mis recetas"}
          </button>
          <p className="text-center text-xs text-[var(--color-muted)]">
            Guárdala para poder cambiar las raciones o los ingredientes, y para usarla en tu
            plan de dieta.
          </p>

          {recipe.attribution && (
            <p className="text-center text-xs text-[var(--color-muted)]">
              {recipe.attribution}
            </p>
          )}
        </div>
      )}
    </BottomSheet>
  );
}

/** Recetario compartido: platos con foto, ingredientes y pasos que vienen con la app.
 *
 * Las calorías se calculan con el catálogo de alimentos de MyFood, no las da la fuente de las
 * recetas: por eso se puede confiar en ellas igual que en las de cualquier otro registro. */
export function RecipeCatalog() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [cuisine, setCuisine] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [items, setItems] = useState<CatalogRecipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<CatalogRecipe | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(query), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  const load = useCallback(
    async (offset: number) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
        if (debounced.trim()) params.set("q", debounced.trim());
        if (cuisine) params.set("cuisine", cuisine);
        if (category) params.set("category", category);
        const res = await apiFetch<CatalogPage>(`/api/recipes/catalog?${params}`);
        setPage(res);
        setItems((prev) => (offset === 0 ? res.items : [...prev, ...res.items]));
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [debounced, cuisine, category],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-lg font-extrabold tracking-tight">Recetario</h2>
        <p className="text-xs text-[var(--color-muted)]">
          Platos con sus ingredientes y sus pasos. Las calorías las calcula MyFood con su
          propio catálogo de alimentos.
        </p>
      </div>

      <label className="relative block">
        <span className="sr-only">Buscar una receta</span>
        <Search
          size={18}
          aria-hidden="true"
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[var(--color-muted)]"
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Busca un plato…"
          className="h-12 w-full rounded-full pl-11 pr-11 text-[15px] shadow-[var(--shadow-card)]"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Borrar la búsqueda"
            className="absolute right-2 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full text-[var(--color-muted)] hover:bg-[var(--color-surface-2)]"
          >
            <X size={18} aria-hidden="true" />
          </button>
        )}
      </label>

      <Chips
        label="Tipo de plato"
        options={page?.categories ?? []}
        selected={category}
        onSelect={setCategory}
      />
      <Chips
        label="Cocina"
        options={page?.cuisines ?? []}
        selected={cuisine}
        onSelect={setCuisine}
      />

      {error ? (
        <ErrorState message={error} onRetry={() => void load(0)} />
      ) : loading && items.length === 0 ? (
        <Skeleton lines={6} />
      ) : items.length === 0 ? (
        <EmptyState message="No hay recetas con esa búsqueda." />
      ) : (
        <>
          <p role="status" aria-live="polite" className="text-sm text-[var(--color-muted)]">
            {page?.total ?? 0} {page?.total === 1 ? "receta" : "recetas"}
          </p>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((recipe) => (
              <RecipeCard key={recipe.id} recipe={recipe} onOpen={() => setOpen(recipe)} />
            ))}
          </ul>
          {page && items.length < page.total && (
            <button
              type="button"
              onClick={() => void load(items.length)}
              disabled={loading}
              className="min-h-12 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold disabled:opacity-60"
            >
              {loading ? "Cargando…" : "Ver más recetas"}
            </button>
          )}
        </>
      )}

      <RecipeSheet
        recipeId={open?.id ?? null}
        fallbackName={open?.name}
        onClose={() => setOpen(null)}
      />
    </section>
  );
}
