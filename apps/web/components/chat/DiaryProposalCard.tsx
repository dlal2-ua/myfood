"use client";

import { Check, Sparkles, TriangleAlert, X } from "lucide-react";
import { MEAL_TYPE_LABELS, type ChatDiaryPayload } from "@/lib/types";

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

/** Lo que el chat va a apuntar, antes de apuntarlo: la petición con las palabras del usuario,
 * cada ingrediente con sus gramos y sus calorías, y el total.
 *
 * Una sola confirmación para todo el mensaje (decisión del usuario): se acepta o se rechaza
 * el conjunto. Las líneas cuyos números puso el modelo, porque el ingrediente no está en el
 * catálogo, salen marcadas: así se ve qué parte del día no viene de un dato oficial. */
export function DiaryProposalCard({
  payload,
  deciding,
  onDecide,
}: {
  payload: ChatDiaryPayload;
  deciding: boolean;
  onDecide: (decision: "approve" | "reject") => void;
}) {
  const macros = [
    ["Proteína", payload.totals.protein_g, "var(--color-protein)"],
    ["Carbos", payload.totals.carbs_g, "var(--color-carbs)"],
    ["Grasa", payload.totals.fat_g, "var(--color-fat)"],
  ] as const;

  return (
    <div className="self-start w-full max-w-[95%] rounded-[var(--radius-card)] border border-[var(--color-primary)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-card)]">
      <p className="text-sm font-extrabold">¿Aceptas este cambio?</p>
      {payload.meal_type && payload.items.length > 0 && (
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">
          Se apuntará en <b>{MEAL_TYPE_LABELS[payload.meal_type].toLowerCase()}</b> de{" "}
          {niceDate(payload.date)}.
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
          <li key={`${item.name}-${i}`} className="flex flex-wrap items-baseline gap-x-2 py-2">
            <span className="min-w-0 flex-1 text-sm font-semibold">
              {item.name}
              {item.estimated && (
                <span
                  title="Este ingrediente no está en el catálogo: los valores los ha estimado Claude."
                  className="ml-1.5 inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-900 dark:bg-amber-950 dark:text-amber-200"
                >
                  <Sparkles size={9} aria-hidden="true" /> estimado
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
            <span className="w-16 text-right text-sm font-bold">{Math.round(item.kcal)} kcal</span>
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
            {Math.round(payload.totals.kcal)} kcal
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
        <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-800 dark:text-amber-300">
          <TriangleAlert size={13} aria-hidden="true" className="mt-px shrink-0" />
          Hay ingredientes que no están en el catálogo: esos números los ha estimado Claude y
          quedarán marcados en tu diario.
        </p>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={deciding}
          onClick={() => onDecide("reject")}
          className="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold disabled:opacity-60"
        >
          <X size={15} aria-hidden="true" /> No
        </button>
        <button
          type="button"
          disabled={deciding}
          onClick={() => onDecide("approve")}
          className="inline-flex min-h-11 flex-[2] items-center justify-center gap-1.5 rounded-full bg-[var(--color-primary)] text-sm font-bold text-[var(--color-on-primary)] disabled:opacity-60"
        >
          <Check size={15} aria-hidden="true" />
          {deciding ? "Apuntando…" : "Sí, apúntalo"}
        </button>
      </div>
    </div>
  );
}
