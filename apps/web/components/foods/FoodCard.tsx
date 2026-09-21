import { Plus } from "lucide-react";
import Link from "next/link";
import { FoodImage } from "@/components/FoodImage";
import { ScoreBadges } from "@/components/ScoreBadges";
import { brandLabel, grams } from "@/lib/foodDisplay";
import type { FoodSearchItem } from "@/lib/types";

function Macros({ item }: { item: FoodSearchItem }) {
  const dot = (color: string) => (
    <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: color }} />
  );
  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs text-[var(--color-muted)]">
      <span className="font-semibold text-[var(--color-text)]">
        {item.kcal_100g != null ? `${Math.round(item.kcal_100g)} kcal` : "—"}
      </span>
      <span className="inline-flex items-center gap-1">{dot("var(--color-protein)")} P {grams(item.protein_100g)}</span>
      <span className="inline-flex items-center gap-1">{dot("var(--color-carbs)")} C {grams(item.carbs_100g)}</span>
      <span className="inline-flex items-center gap-1">{dot("var(--color-fat)")} G {grams(item.fat_100g)}</span>
    </span>
  );
}

/** Botón de «añadir al diario» de una tarjeta. Va SUPERPUESTO al enlace, no dentro: un
 * <button> dentro de un <a> no es HTML válido y el navegador lo desmonta. */
function AddButton({ onAdd, name }: { onAdd: () => void; name: string }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onAdd();
      }}
      aria-label={`Añadir ${name} al diario`}
      className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[var(--color-primary-soft)] text-[var(--color-primary)] transition-colors hover:bg-[var(--color-primary)] hover:text-[var(--color-on-primary)]"
    >
      <Plus size={20} aria-hidden="true" />
    </button>
  );
}

/** Alimento en una lista: foto, nombre, dónde se vende y macros por 100 g, con un botón para
 * registrarlo sin salir de la lista. */
export function FoodRow({ item, onAdd }: { item: FoodSearchItem; onAdd?: () => void }) {
  const brand = brandLabel(item.brand, item.supermarket);
  return (
    <div className="relative">
    <Link
      href={`/foods/${item.id}`}
      className="flex items-center gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 pr-16 shadow-[var(--shadow-card)] transition-colors hover:border-[var(--color-primary)]"
    >
      <FoodImage foodId={item.id} size={200} px={60} className="rounded-2xl" />
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-[15px] font-bold leading-snug">{item.name_es}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
          {item.supermarket && (
            <span className="rounded-full bg-[var(--color-primary-soft)] px-2 py-0.5 text-[11px] font-bold text-[var(--color-primary)]">
              {item.supermarket}
            </span>
          )}
          {brand && <span className="truncate text-xs text-[var(--color-muted)]">{brand}</span>}
          {!item.supermarket && !brand && item.food_type && (
            <span className="text-xs text-[var(--color-muted)]">{item.food_type}</span>
          )}
        </span>
        <span className="mt-1 block">
          <Macros item={item} />
        </span>
        <span className="mt-1 block">
          <ScoreBadges nutriscore={item.nutriscore_grade} nova={item.nova_group} ecoscore={item.ecoscore_grade} />
        </span>
      </span>
    </Link>
      {onAdd && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2">
          <AddButton onAdd={onAdd} name={item.name_es} />
        </span>
      )}
    </div>
  );
}

/** Alimento en una fila horizontal de sugerencias: tarjeta vertical y estrecha. */
export function FoodTile({ item, onAdd }: { item: FoodSearchItem; onAdd?: () => void }) {
  const brand = brandLabel(item.brand, item.supermarket);
  return (
    <div className="relative flex">
    <Link
      href={`/foods/${item.id}`}
      className="flex w-40 shrink-0 flex-col gap-2 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 shadow-[var(--shadow-card)] transition-colors hover:border-[var(--color-primary)]"
    >
      <FoodImage foodId={item.id} size={200} px={64} className="rounded-2xl" />
      <span className="line-clamp-2 min-h-[2.5rem] text-sm font-bold leading-snug">{item.name_es}</span>
      {(item.supermarket || brand) && (
        <span className="truncate text-xs text-[var(--color-muted)]">{item.supermarket ?? brand}</span>
      )}
      <span className="text-xs text-[var(--color-muted)]">
        <span className="font-semibold text-[var(--color-text)]">
          {item.kcal_100g != null ? `${Math.round(item.kcal_100g)} kcal` : "—"}
        </span>{" "}
        · P {grams(item.protein_100g)}
      </span>
    </Link>
      {onAdd && (
        <span className="absolute bottom-2 right-2">
          <AddButton onAdd={onAdd} name={item.name_es} />
        </span>
      )}
    </div>
  );
}
