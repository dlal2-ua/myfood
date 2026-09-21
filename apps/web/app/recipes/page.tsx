"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { LogRecipeForm } from "@/components/LogRecipeForm";
import { UserImageUpload } from "@/components/UserImageUpload";
import { FoodSearchBox } from "@/components/FoodSearchBox";
import type {
  AiSession,
  FoodSearchItem,
  Recipe,
  RecipeImportDraft,
  RecipeImportIngredient,
  RecipeSummary,
} from "@/lib/types";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

// Importar una receta hace una llamada al agente POR CADA línea de
// ingrediente (sección 20 — cada línea pasa por el mismo resolutor que
// Smart Log, no una única llamada para toda la receta), así que puede
// tardar más que el resto de iafood: 90 × 2s = 180s.
const IMPORT_MAX_POLL_ATTEMPTS = 90;
const POLL_INTERVAL_MS = 2000;

interface NewIngredientRow {
  food: FoodSearchItem;
  grams: string;
}

interface DraftIngredientRow extends RecipeImportIngredient {
  gramsInput: string;
  include: boolean;
}

export default function RecipesPage() {
  const [recipes, setRecipes] = useState<RecipeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Recipe | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  // --- crear manualmente ---
  const [newName, setNewName] = useState("");
  const [newServings, setNewServings] = useState("1");
  const [newPrepMinutes, setNewPrepMinutes] = useState("");
  const [newInstructions, setNewInstructions] = useState("");
  const [newIngredients, setNewIngredients] = useState<NewIngredientRow[]>([]);
  const [pickedFood, setPickedFood] = useState<FoodSearchItem | null>(null);
  const [pickedGrams, setPickedGrams] = useState("100");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // --- importar desde URL ---
  const [importUrl, setImportUrl] = useState("");
  const [importConsent, setImportConsent] = useState(false);
  const [importRequesting, setImportRequesting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importDraft, setImportDraft] = useState<DraftIngredientRow[] | null>(null);
  const [importMeta, setImportMeta] = useState<
    Pick<RecipeImportDraft, "name" | "servings" | "prep_minutes" | "instructions" | "unresolved_lines">
    | null
  >(null);
  const [savingDraft, setSavingDraft] = useState(false);
  // Fila del borrador cuyo alimento se está cambiando; `addingFor` = línea sin resolver que se
  // está resolviendo a mano (cadena vacía = ingrediente extra sin línea de origen).
  const [changingIndex, setChangingIndex] = useState<number | null>(null);
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const importPollCountRef = useRef(0);

  async function loadRecipes() {
    setLoading(true);
    setError(null);
    try {
      setRecipes(await apiFetch<RecipeSummary[]>("/api/recipes"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadRecipes();
  }, []);

  async function loadDetail(id: string) {
    setSelectedId(id);
    setDetailError(null);
    try {
      setSelected(await apiFetch<Recipe>(`/api/recipes/${id}`));
    } catch (err) {
      setDetailError(errorMessage(err));
    }
  }

  async function onDeleteRecipe(id: string) {
    if (!confirm("¿Eliminar esta receta?")) return;
    try {
      await apiFetch(`/api/recipes/${id}`, { method: "DELETE" });
      if (selectedId === id) {
        setSelectedId(null);
        setSelected(null);
      }
      await loadRecipes();
    } catch (err) {
      setDetailError(errorMessage(err));
    }
  }

  async function onUpdateIngredientGrams(ingredientId: string, grams: string) {
    if (!selected) return;
    const ingredient = selected.ingredients.find((i) => i.id === ingredientId);
    if (!ingredient) return;
    try {
      const updated = await apiFetch<Recipe>(
        `/api/recipes/${selected.id}/ingredients/${ingredientId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ food_id: ingredient.food_id, grams: Number(grams) }),
        },
      );
      setSelected(updated);
    } catch (err) {
      setDetailError(errorMessage(err));
    }
  }

  async function onRemoveIngredient(ingredientId: string) {
    if (!selected) return;
    try {
      await apiFetch(`/api/recipes/${selected.id}/ingredients/${ingredientId}`, {
        method: "DELETE",
      });
      await loadDetail(selected.id);
    } catch (err) {
      setDetailError(errorMessage(err));
    }
  }

  function addPickedFoodToNewIngredients() {
    if (!pickedFood) return;
    setNewIngredients((prev) => [...prev, { food: pickedFood, grams: pickedGrams }]);
    setPickedFood(null);
    setPickedGrams("100");
  }

  function removeNewIngredient(index: number) {
    setNewIngredients((prev) => prev.filter((_, i) => i !== index));
  }

  async function onCreateRecipe(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await apiFetch("/api/recipes", {
        method: "POST",
        body: JSON.stringify({
          name: newName,
          servings: Number(newServings) || 1,
          prep_minutes: newPrepMinutes ? Number(newPrepMinutes) : null,
          instructions: newInstructions || null,
          ingredients: newIngredients.map((row) => ({
            food_id: row.food.id,
            grams: Number(row.grams),
          })),
        }),
      });
      setNewName("");
      setNewServings("1");
      setNewPrepMinutes("");
      setNewInstructions("");
      setNewIngredients([]);
      await loadRecipes();
    } catch (err) {
      setCreateError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function pollImportSession(sessionId: string) {
    importPollCountRef.current = 0;
    const tick = async () => {
      importPollCountRef.current += 1;
      let session: AiSession;
      try {
        session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
      } catch (err) {
        setImportError(errorMessage(err));
        return;
      }
      if (session.status === "running") {
        if (importPollCountRef.current >= IMPORT_MAX_POLL_ATTEMPTS) {
          setImportError("La importación está tardando más de lo esperado. Inténtalo de nuevo.");
          return;
        }
        setTimeout(() => void tick(), POLL_INTERVAL_MS);
        return;
      }
      if (session.status !== "succeeded") {
        const detail = session.validation_errors?.[0]?.message;
        setImportError(detail ?? "No se ha podido importar la receta.");
        return;
      }
      const draft = session.response_payload as unknown as RecipeImportDraft;
      setImportMeta({
        name: draft.name,
        servings: draft.servings,
        prep_minutes: draft.prep_minutes,
        instructions: draft.instructions,
        unresolved_lines: draft.unresolved_lines,
      });
      setImportDraft(
        draft.ingredients.map((item) => ({
          ...item,
          gramsInput: String(item.grams),
          include: true,
        })),
      );
    };
    await tick();
  }

  async function onImportSubmit(e: React.FormEvent) {
    e.preventDefault();
    setImportRequesting(true);
    setImportError(null);
    setImportDraft(null);
    setImportMeta(null);
    try {
      if (importConsent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const session = await apiFetch<AiSession>("/api/recipes/import-url", {
        method: "POST",
        body: JSON.stringify({ url: importUrl }),
      });
      await pollImportSession(session.id);
    } catch (err) {
      setImportError(errorMessage(err));
    } finally {
      setImportRequesting(false);
    }
  }

  function updateDraftRow(index: number, patch: Partial<DraftIngredientRow>) {
    setImportDraft((prev) =>
      prev ? prev.map((row, i) => (i === index ? { ...row, ...patch } : row)) : prev,
    );
  }

  function onChangeDraftFood(index: number, food: FoodSearchItem) {
    updateDraftRow(index, { food_id: food.id, name_es: food.name_es });
    setChangingIndex(null);
  }

  function onAddDraftIngredient(line: string, food: FoodSearchItem) {
    setImportDraft((prev) => [
      ...(prev ?? []),
      {
        food_id: food.id,
        name_es: food.name_es,
        grams: 100,
        gramsInput: "100",
        approx_quantity_text: "",
        original_line: line,
        include: true,
      },
    ]);
    if (line) {
      setImportMeta((prev) =>
        prev ? { ...prev, unresolved_lines: prev.unresolved_lines.filter((l) => l !== line) } : prev,
      );
    }
    setAddingFor(null);
  }

  async function onSaveDraft() {
    if (!importDraft || !importMeta) return;
    setSavingDraft(true);
    setImportError(null);
    try {
      await apiFetch("/api/recipes", {
        method: "POST",
        body: JSON.stringify({
          name: importMeta.name,
          servings: importMeta.servings,
          prep_minutes: importMeta.prep_minutes,
          instructions: importMeta.instructions,
          ingredients: importDraft
            .filter((row) => row.include)
            .map((row) => ({ food_id: row.food_id, grams: Number(row.gramsInput) })),
        }),
      });
      setImportDraft(null);
      setImportMeta(null);
      setImportUrl("");
      await loadRecipes();
    } catch (err) {
      setImportError(errorMessage(err));
    } finally {
      setSavingDraft(false);
    }
  }

  return (
    <main className="flex flex-col gap-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Recetas</h1>

      <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <h2 className="mb-3 text-lg font-semibold">Importar desde URL</h2>
        <p className="mb-3 text-sm text-neutral-500">
          Pega el enlace de una receta y Claude interpretará cada ingrediente (nunca
          gramos exactos) contra el catálogo — revisas y ajustas antes de guardar nada.
        </p>
        <form onSubmit={onImportSubmit} className="flex flex-wrap items-end gap-3">
          <input
            type="url"
            required
            placeholder="https://..."
            className={`${inputClass} min-w-[16rem] flex-1`}
            value={importUrl}
            onChange={(e) => setImportUrl(e.target.value)}
          />
          <button
            type="submit"
            disabled={importRequesting}
            className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {importRequesting ? "Importando…" : "Importar"}
          </button>
        </form>
        <label className="mt-2 flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={importConsent}
            onChange={(e) => setImportConsent(e.target.checked)}
            className="mt-0.5"
          />
          Acepto que el contenido de esa página se envíe a Claude para interpretarlo.
        </label>

        {importError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{importError}</p>}

        {importMeta && importDraft && (
          <div className="mt-4 flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
            <p className="text-sm font-medium">
              {importMeta.name} · {importMeta.servings} raciones
              {importMeta.prep_minutes != null && ` · ${importMeta.prep_minutes} min`}
            </p>
            {importDraft.map((row, index) => (
              <div key={`${row.food_id}-${index}`} className="flex flex-wrap items-end gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={row.include}
                    onChange={(e) => updateDraftRow(index, { include: e.target.checked })}
                  />
                  {row.name_es}
                </label>
                {row.original_line && (
                  <span className="text-xs text-neutral-500">&quot;{row.original_line}&quot;</span>
                )}
                <label className="flex flex-col gap-1 text-sm">
                  Gramos
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={row.gramsInput}
                    onChange={(e) => updateDraftRow(index, { gramsInput: e.target.value })}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setChangingIndex(changingIndex === index ? null : index)}
                  className="text-sm text-neutral-500 underline"
                >
                  {changingIndex === index ? "Cancelar" : "Cambiar alimento"}
                </button>
                {changingIndex === index && (
                  <div className="w-full">
                    <FoodSearchBox onSelect={(food) => onChangeDraftFood(index, food)} />
                  </div>
                )}
              </div>
            ))}
            {importMeta.unresolved_lines.length > 0 && (
              <div className="flex flex-col gap-2 text-sm">
                <p className="font-medium">Líneas que no se han podido resolver</p>
                {importMeta.unresolved_lines.map((line) => (
                  <div key={line} className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-neutral-600 dark:text-neutral-400">
                        &quot;{line}&quot;
                      </span>
                      <button
                        type="button"
                        onClick={() => setAddingFor(addingFor === line ? null : line)}
                        className="text-neutral-500 underline"
                      >
                        {addingFor === line ? "Cancelar" : "Buscar alimento"}
                      </button>
                    </div>
                    {addingFor === line && (
                      <FoodSearchBox onSelect={(food) => onAddDraftIngredient(line, food)} />
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="flex flex-col gap-2 text-sm">
              <button
                type="button"
                onClick={() => setAddingFor(addingFor === "" ? null : "")}
                className="self-start text-neutral-500 underline"
              >
                {addingFor === "" ? "Cancelar" : "Añadir otro ingrediente"}
              </button>
              {addingFor === "" && (
                <FoodSearchBox onSelect={(food) => onAddDraftIngredient("", food)} />
              )}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={savingDraft}
                onClick={() => void onSaveDraft()}
                className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
              >
                {savingDraft ? "Guardando…" : "Guardar receta"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setImportDraft(null);
                  setImportMeta(null);
                }}
                className="text-sm text-neutral-500 underline"
              >
                Descartar
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <h2 className="mb-3 text-lg font-semibold">Crear receta manualmente</h2>
        <form onSubmit={onCreateRecipe} className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-3">
            <input
              type="text"
              required
              placeholder="Nombre"
              className={`${inputClass} min-w-[12rem] flex-1`}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <label className="flex flex-col gap-1 text-sm">
              Raciones
              <input
                type="number"
                min={1}
                className={inputClass}
                value={newServings}
                onChange={(e) => setNewServings(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Minutos
              <input
                type="number"
                min={0}
                className={inputClass}
                value={newPrepMinutes}
                onChange={(e) => setNewPrepMinutes(e.target.value)}
              />
            </label>
          </div>
          <textarea
            placeholder="Instrucciones (opcional)"
            className={inputClass}
            rows={3}
            value={newInstructions}
            onChange={(e) => setNewInstructions(e.target.value)}
          />

          <div>
            <p className="mb-2 text-sm font-medium">Ingredientes</p>
            <FoodSearchBox onSelect={setPickedFood} />
            {pickedFood && (
              <div className="mt-2 flex flex-wrap items-end gap-3">
                <p className="text-sm">
                  Elegido: <span className="font-medium">{pickedFood.name_es}</span>
                </p>
                <label className="flex flex-col gap-1 text-sm">
                  Gramos
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={pickedGrams}
                    onChange={(e) => setPickedGrams(e.target.value)}
                  />
                </label>
                <button
                  type="button"
                  onClick={addPickedFoodToNewIngredients}
                  className="rounded-full bg-[var(--color-primary)] px-3 py-1.5 text-sm text-[var(--color-on-primary)] font-semibold hover:bg-[var(--color-primary-hover)]"
                >
                  Añadir a la receta
                </button>
              </div>
            )}
            {newIngredients.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1">
                {newIngredients.map((row, index) => (
                  <li key={index} className="flex items-center justify-between gap-3 text-sm">
                    <span>
                      {row.food.name_es} · {row.grams} g
                    </span>
                    <button
                      type="button"
                      onClick={() => removeNewIngredient(index)}
                      className="text-red-600 dark:text-red-400 underline"
                    >
                      Quitar
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <button
            type="submit"
            disabled={creating}
            className="w-fit rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {creating ? "Creando…" : "Crear receta"}
          </button>
          {createError && <p className="text-sm text-red-600 dark:text-red-400">{createError}</p>}
        </form>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Mis recetas</h2>
        {loading && <Skeleton lines={3} />}
        {error && <ErrorState message={error} onRetry={() => void loadRecipes()} />}
        {!loading && recipes.length === 0 && (
          <EmptyState message="Todavía no tienes recetas. Crea una a mano o impórtala desde una URL." />
        )}
        <ul className="divide-y divide-[var(--color-border)]">
          {recipes.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 py-2">
              <button
                type="button"
                onClick={() => void loadDetail(r.id)}
                className="text-left text-sm underline"
              >
                {r.name}
                <span className="ml-2 text-xs text-neutral-500">
                  {r.servings} raciones{r.prep_minutes != null && ` · ${r.prep_minutes} min`}
                </span>
              </button>
              <button
                type="button"
                onClick={() => void onDeleteRecipe(r.id)}
                className="text-sm text-red-600 dark:text-red-400 underline"
              >
                Eliminar
              </button>
            </li>
          ))}
        </ul>

        {selectedId && (
          <div className="mt-4 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
            {detailError && <p className="text-sm text-red-600 dark:text-red-400">{detailError}</p>}
            {selected && (
              <>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-lg font-semibold">{selected.name}</h3>
                  <UserImageUpload
                    imageUrl={selected.image_url}
                    endpoint={`/api/recipes/${selected.id}`}
                    alt={`Foto de ${selected.name}`}
                    onChanged={() => void loadDetail(selected.id)}
                  />
                </div>
                {selected.instructions && (
                  <p className="mt-1 whitespace-pre-line text-sm text-neutral-600 dark:text-neutral-400">
                    {selected.instructions}
                  </p>
                )}
                <ul className="mt-3 flex flex-col gap-2">
                  {selected.ingredients.map((ing) => (
                    <li key={ing.id} className="flex flex-wrap items-center gap-3 text-sm">
                      <span className="min-w-[10rem]">{ing.name_es}</span>
                      <input
                        type="number"
                        min={1}
                        className={inputClass}
                        defaultValue={ing.grams}
                        onBlur={(e) => void onUpdateIngredientGrams(ing.id, e.target.value)}
                      />
                      <span className="text-neutral-500">{ing.kcal} kcal</span>
                      <button
                        type="button"
                        onClick={() => void onRemoveIngredient(ing.id)}
                        className="text-red-600 dark:text-red-400 underline"
                      >
                        Quitar
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="mt-4 flex gap-6 text-sm">
                  <div>
                    <p className="text-neutral-500">Total</p>
                    <p className="font-semibold">{selected.totals.kcal} kcal</p>
                  </div>
                  <div>
                    <p className="text-neutral-500">Por ración</p>
                    <p className="font-semibold">{selected.totals_per_serving.kcal} kcal</p>
                  </div>
                </div>
                <LogRecipeForm recipe={selected} />
              </>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
