"use client";

import { BadgeCheck, BookmarkCheck, Check, X } from "lucide-react";
import { useState } from "react";
import { CollapsibleNotice } from "@/components/Notices";
import { MEAL_TYPE_LABELS, type ChatDiaryPayload, type DiaryProposalItem } from "@/lib/types";

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function niceDate(iso: string): string {
  const day = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(day.getTime())) return iso;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((day.getTime() - today.getTime()) / 86400000);
  if (diff === 0) return "hoy";
  if (diff === -1) return "ayer";
  return `el ${day.getDate()} de ${MONTHS[day.getMonth()]}`;
}

/** Solo el dominio: la URL entera no cabe y lo que importa es de quién es el dato. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "fuente";
  }
}

function n(value: number): string {
  return String(Math.round(value * 10) / 10).replace(".", ",");
}

/** «aprox. 260 kcal» para lo estimado, «260 kcal» para lo que viene del catálogo. Una
 * estimación no se enseña nunca con la misma cara que un dato oficial. */
function kcalLabel(kcal: number, estimated: boolean): string {
  return `${estimated ? "aprox. " : ""}${Math.round(kcal)} kcal`;
}

/** Se puede guardar lo que ha estimado el modelo y todavía no tiene ficha en el catálogo. */
function canSave(item: DiaryProposalItem): boolean {
  return item.estimated && !item.food_id;
}

/** Lo que se va a apuntar, antes de apuntarlo: la petición con las palabras del usuario, cada
 * plato con sus calorías y de qué se compone, y el total. La usan igual el chat (escrito o
 * dictado) y el registro por texto del diario.
 *
 * Una sola confirmación para todo el mensaje (decisión del usuario): se acepta o se rechaza
 * el conjunto. Cada plato estimado se puede, además, guardar en el catálogo: la próxima vez
 * que se nombre se reutiliza esa estimación en vez de volver a pedírsela al modelo. */
export function DiaryProposalCard({
  payload,
  deciding,
  onDecide,
}: {
  payload: ChatDiaryPayload;
  deciding: boolean;
  /** `saveToCatalog`: posiciones de `payload.items` que el usuario quiere guardar. */
  onDecide: (decision: "approve" | "reject", saveToCatalog: number[]) => void;
}) {
  const [toSave, setToSave] = useState<Set<number>>(new Set());

  const macros = [
    ["Proteína", payload.totals.protein_g, "var(--color-protein)"],
    ["Carbos", payload.totals.carbs_g, "var(--color-carbs)"],
    ["Grasa", payload.totals.fat_g, "var(--color-fat)"],
  ] as const;

  // Si el mensaje reparte entre varias comidas, cada plato dice la suya.
  const mealTypes = new Set(payload.items.map((item) => item.meal_type ?? payload.meal_type));
  const splitAcrossMeals = mealTypes.size > 1;
  const singleMeal = [...mealTypes][0] ?? payload.meal_type;
  const anySavable = payload.items.some(canSave);
  const hasCatalogValues = payload.items.some(
    (item) => item.catalog || item.components?.some((component) => component.catalog),
  );

  function toggleSave(index: number) {
    setToSave((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  return (
    <div className="self-start w-full max-w-[95%] rounded-[var(--radius-card)] border border-[var(--color-primary)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-card)]">
      <p className="text-sm font-extrabold">¿Lo apunto así?</p>
      {singleMeal && payload.items.length > 0 && (
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">
          {splitAcrossMeals ? (
            <>Se apuntará {niceDate(payload.date)}, cada plato en su comida.</>
          ) : (
            <>
              Se apuntará en <b>{MEAL_TYPE_LABELS[singleMeal].toLowerCase()}</b> de{" "}
              {niceDate(payload.date)}.
            </>
          )}
        </p>
      )}
      {payload.request && (
        <p className="mt-2 rounded-[var(--radius-control)] bg-[var(--color-surface-2)] px-3 py-2 text-sm italic">
          «{payload.request}»
        </p>
      )}

      {payload.items.length > 0 && (
        <ul className="mt-3 divide-y divide-[var(--color-border)]">
          {payload.items.map((item, i) => (
            <li key={`${item.name}-${i}`} className="py-2">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="min-w-0 flex-1 text-sm font-semibold">
                  {item.name}
                  {item.quantity != null && item.quantity !== 1 && (
                    <span className="ml-1 font-normal text-[var(--color-muted)]">
                      ×{n(item.quantity)}
                    </span>
                  )}
                  {item.from_catalog && (
                    <span
                      title="Este plato ya estaba guardado en el catálogo: se usan sus números."
                      className="ml-1.5 inline-flex items-center gap-1 rounded-full bg-[var(--color-primary-soft)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--color-primary)]"
                    >
                      <BookmarkCheck size={9} aria-hidden="true" /> guardado
                    </span>
                  )}
                </span>
                {item.source_url && (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-[11px] text-[var(--color-muted)] underline"
                    title={item.source_url}
                  >
                    {hostOf(item.source_url)}
                  </a>
                )}
                <span className="text-xs text-[var(--color-muted)]">{n(item.grams)} g</span>
                <span className="text-right text-sm font-bold">
                  {kcalLabel(item.kcal, item.estimated)}
                </span>
              </div>

              {splitAcrossMeals && item.meal_type && (
                <p className="text-[11px] font-semibold text-[var(--color-primary)]">
                  {MEAL_TYPE_LABELS[item.meal_type]}
                </p>
              )}

              {item.catalog && (
                <p
                  className="mt-0.5 flex items-center gap-1 text-[11px] text-[var(--color-muted)]"
                  title={`Valores por 100 g del catálogo: ${item.catalog}`}
                >
                  <BadgeCheck size={11} aria-hidden="true" className="text-[var(--color-primary)]" />
                  valores del catálogo
                </p>
              )}

              {item.components && item.components.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5 text-xs text-[var(--color-muted)]">
                  {item.components.map((component, ci) => (
                    <li key={`${component.name}-${ci}`} className="flex items-baseline gap-1.5">
                      <span className="min-w-0 flex-1">
                        {component.name}
                        {component.catalog && (
                          <BadgeCheck
                            size={11}
                            role="img"
                            aria-label="Valores del catálogo"
                            className="ml-1 inline-block align-[-1px] text-[var(--color-primary)]"
                          >
                            <title>{`Valores por 100 g del catálogo: ${component.catalog}`}</title>
                          </BadgeCheck>
                        )}
                      </span>
                      {component.grams != null && <span>{n(component.grams)} g</span>}
                      {component.kcal != null && (
                        <span className="w-16 text-right">{Math.round(component.kcal)} kcal</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {canSave(item) && (
                <label className="mt-1.5 flex min-h-6 items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={toSave.has(i)}
                    onChange={() => toggleSave(i)}
                    disabled={deciding}
                  />
                  Guardar «{item.name}» en el catálogo
                </label>
              )}
            </li>
          ))}
        </ul>
      )}

      {payload.edits && payload.edits.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 text-sm">
          {payload.edits.map((edit) => (
            <li key={edit.entry_id} className="flex flex-wrap items-baseline gap-2">
              <span className="font-semibold">
                {edit.action === "delete" ? "Quitar" : "Cambiar"}: {edit.name}
              </span>
              {edit.action === "update" && edit.grams != null && (
                <span className="text-xs text-[var(--color-muted)]">
                  a {n(edit.grams)} g{edit.kcal != null ? ` · ${Math.round(edit.kcal)} kcal` : ""}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {payload.water && (
        <p className="mt-3 text-sm font-semibold">
          Apuntar {payload.water.ml} ml de agua{" "}
          <span className="text-xs font-normal text-[var(--color-muted)]">
            ({niceDate(payload.water.date)})
          </span>
        </p>
      )}

      {payload.shopping && payload.shopping.length > 0 && (
        <div className="mt-3 text-sm">
          <p className="font-semibold">A la lista de la compra:</p>
          <p className="text-[var(--color-muted)]">
            {payload.shopping.map((i) => i.text).join(", ")}
          </p>
        </div>
      )}

      {payload.items.length > 0 && (
        <div className="mt-2 rounded-[var(--radius-control)] bg-[var(--color-primary-soft)] px-3 py-2">
          <p className="flex items-baseline justify-between">
            <span className="text-sm font-bold text-[var(--color-primary)]">Total</span>
            <span className="text-xl font-extrabold tracking-tight text-[var(--color-primary)]">
              {kcalLabel(payload.totals.kcal, payload.has_estimates)}
            </span>
          </p>
          <ul className="mt-1 flex flex-wrap gap-x-4 text-xs">
            {macros.map(([label, value, color]) => (
              <li key={label} className="flex items-center gap-1">
                <span
                  aria-hidden="true"
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: color }}
                />
                {label} <b>{n(value)} g</b>
              </li>
            ))}
          </ul>
        </div>
      )}

      {payload.has_estimates && (
        <CollapsibleNotice id="estimate-note" title="Estimación orientativa" className="mt-2">
          Es una estimación orientativa, no una medición: las cantidades son a ojo.
          {hasCatalogValues && (
            <>
              {" "}
              Lo marcado con{" "}
              <BadgeCheck size={11} aria-hidden="true" className="inline-block align-[-1px]" /> toma
              sus valores por 100 g del catálogo.
            </>
          )}
          {anySavable && (
            <> Lo que guardes en el catálogo se reutiliza la próxima vez que lo nombres.</>
          )}
        </CollapsibleNotice>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={deciding}
          onClick={() => onDecide("reject", [])}
          className="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold disabled:opacity-60"
        >
          <X size={15} aria-hidden="true" /> No
        </button>
        <button
          type="button"
          disabled={deciding}
          onClick={() => onDecide("approve", [...toSave].sort((a, b) => a - b))}
          className="inline-flex min-h-11 flex-[2] items-center justify-center gap-1.5 rounded-full bg-[var(--color-primary)] text-sm font-bold text-[var(--color-on-primary)] disabled:opacity-60"
        >
          <Check size={15} aria-hidden="true" />
          {deciding ? "Apuntando…" : toSave.size > 0 ? "Sí, apúntalo y guárdalo" : "Sí, apúntalo"}
        </button>
      </div>
    </div>
  );
}
