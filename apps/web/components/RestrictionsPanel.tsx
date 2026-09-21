"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { FoodSearchBox } from "@/components/FoodSearchBox";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import type { Allergen, FoodSearchItem, Restriction, RestrictionKind } from "@/lib/types";
import { Skeleton } from "@/components/ui/states";

const KIND_LABELS: Record<RestrictionKind, string> = {
  allergen: "Alergia",
  intolerance: "Intolerancia",
  disliked_food: "No me gusta",
  banned_food: "Vetado",
};

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

/** Alergias, intolerancias y alimentos vetados o que no te gustan. El generador de
 * dietas, iafood y el chat los tratan como restricción dura: nunca proponen un
 * alimento con un alérgeno de los que declares aquí. */
export function RestrictionsPanel() {
  const [restrictions, setRestrictions] = useState<Restriction[]>([]);
  const [allergens, setAllergens] = useState<Allergen[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [kind, setKind] = useState<RestrictionKind>("allergen");
  const [allergenCode, setAllergenCode] = useState("");
  const [pickedFood, setPickedFood] = useState<FoodSearchItem | null>(null);

  const byAllergen = kind === "allergen" || kind === "intolerance";

  async function load() {
    try {
      const [rs, as] = await Promise.all([
        apiFetch<{ items: Restriction[] }>("/api/restrictions"),
        apiFetch<{ items: Allergen[] }>("/api/allergens"),
      ]);
      setRestrictions(rs.items);
      setAllergens(as.items);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, string> = { kind };
      if (byAllergen) body.allergen_code = allergenCode;
      else if (pickedFood) body.food_id = pickedFood.id;
      await apiFetch("/api/restrictions", { method: "POST", body: JSON.stringify(body) });
      setAllergenCode("");
      setPickedFood(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(id: string) {
    setError(null);
    try {
      await apiFetch(`/api/restrictions/${id}`, { method: "DELETE" });
      setRestrictions((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const canAdd = byAllergen ? allergenCode !== "" : pickedFood !== null;

  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="text-xl font-semibold">Alergias, intolerancias y alimentos vetados</h2>
        <p className="mt-1 text-sm text-neutral-500">
          Los planes, iafood y el chat nunca te propondrán un alimento con un alérgeno de los que
          marques aquí ni uno de los vetados.
        </p>
      </div>

      {loading && <Skeleton lines={3} />}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {!loading && restrictions.length === 0 && (
        <p className="text-sm text-neutral-500">
          Todavía no has declarado ninguna restricción. Si tienes alguna alergia, añádela aquí
          antes de generar un plan.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {restrictions.map((r) => (
          <li
            key={r.id}
            className="flex items-center justify-between gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] px-3 py-2 text-sm"
          >
            <span>
              <span className="mr-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs uppercase text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                {KIND_LABELS[r.kind]}
              </span>
              {r.allergen_name ?? r.food_name}
            </span>
            <button
              type="button"
              onClick={() => void onRemove(r.id)}
              className="text-neutral-500 underline"
              aria-label={`Quitar restricción ${r.allergen_name ?? r.food_name}`}
            >
              Quitar
            </button>
          </li>
        ))}
      </ul>

      <form onSubmit={onAdd} className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Tipo
            <select
              className={inputClass}
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as RestrictionKind);
                setAllergenCode("");
                setPickedFood(null);
              }}
            >
              {Object.entries(KIND_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {byAllergen && (
            <label className="flex flex-col gap-1 text-sm">
              Alérgeno
              <select
                className={inputClass}
                value={allergenCode}
                onChange={(e) => setAllergenCode(e.target.value)}
              >
                <option value="">Elige uno…</option>
                {allergens.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.name_es}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="submit"
            disabled={busy || !canAdd}
            className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            Añadir
          </button>
        </div>
        {!byAllergen && (
          <div className="flex flex-col gap-2">
            {pickedFood ? (
              <p className="text-sm">
                Alimento elegido: <strong>{pickedFood.name_es}</strong>{" "}
                <button
                  type="button"
                  onClick={() => setPickedFood(null)}
                  className="text-neutral-500 underline"
                >
                  cambiar
                </button>
              </p>
            ) : (
              <FoodSearchBox onSelect={setPickedFood} />
            )}
          </div>
        )}
      </form>

      <MedicalDisclaimer>
        La información de alérgenos de los alimentos es <strong>orientativa</strong>: en los
        productos de marca viene de lo que declara el fabricante (y trazas), y en los alimentos
        genéricos se infiere por su nombre. Revisa siempre la etiqueta del producto que vayas a
        comer, sobre todo si tu alergia es grave.
      </MedicalDisclaimer>
    </section>
  );
}
