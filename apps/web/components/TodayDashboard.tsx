"use client";

import { Camera, Droplets, MessageSquareText, Plus, Search, Timer } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useCurrentUserId } from "@/components/CurrentUser";
import { DATA_CHANGED_EVENT } from "@/components/shell/QuickAddSheet";
import { BudgetRing } from "@/components/ui/BudgetRing";
import { WeekBudget } from "@/components/WeekBudget";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import { onQueueChanged, submitOrQueue } from "@/lib/offlineQueue";
import { diaryMeals, entryName } from "@/lib/today";
import { MEAL_TYPE_LABELS } from "@/lib/types";
import type { Fasting, LogDay, SupplementsToday, TargetsResponse, WaterDay } from "@/lib/types";

interface TodayData {
  log: LogDay;
  targets: TargetsResponse | null;
  water: WaterDay | null;
  supplements: SupplementsToday | null;
  fasting: Fasting | null;
}

const CARD =
  "rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)]";

function MacroProgress({
  label,
  value,
  target,
  color,
}: {
  label: string;
  value: number;
  target: number | null | undefined;
  color: string;
}) {
  const fraction = target && target > 0 ? Math.min(1, Math.max(0, value / target)) : 0;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
        <span className="font-bold">{label}</span>
        <span className="text-[var(--color-muted)]">
          {Math.round(value)}
          {target ? ` / ${Math.round(target)}` : ""} g
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={`${label}: ${Math.round(value)}${target ? ` de ${Math.round(target)}` : ""} g`}
        aria-valuemin={0}
        aria-valuemax={target ? Math.round(target) : undefined}
        aria-valuenow={Math.round(value)}
        className="h-2.5 overflow-hidden rounded-full bg-[var(--color-surface-2)]"
      >
        <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${fraction * 100}%`, background: color }} />
      </div>
    </div>
  );
}

/** Pantalla «Hoy» (sección 14.1): presupuesto de calorías («objetivo − comida = restantes»),
 * macros, agua, suplementos pendientes, ayuno y el diario del día. Los objetivos son orientativos
 * y no se colorean como «bien» o «mal» (R10). El botón «+» de acciones rápidas vive en la barra
 * de la app, no aquí. */
/** Lo que ve alguien que entra y todavía no tiene ni objetivos ni nada apuntado.
 *
 * Antes veía el marcador entero a cero —anillo a 0, «Objetivo —», los tres macros a 0 g— y una
 * caja gris mandándole a rellenar el perfil; los botones de apuntar quedaban por debajo del
 * pliegue, detrás del agua y los suplementos. Cinco de los ocho primeros usuarios se
 * registraron y no apuntaron nunca nada. Un marcador vacío no es información: es ruido, así
 * que aquí se sustituye por lo único que hay que hacer el primer día.
 */
function PrimerDia() {
  const accesos = [
    { href: "/log#foto", icon: Camera, label: "Foto del plato", hint: "La más rápida" },
    { href: "/log#natural", icon: MessageSquareText, label: "Escribirlo", hint: "«dos huevos y una tostada»" },
    { href: "/foods", icon: Search, label: "Buscarlo", hint: "En el catálogo" },
  ];
  return (
    <section className="flex flex-col gap-4">
      <div className={`${CARD} p-5`}>
        <h2 className="text-xl font-extrabold tracking-tight">Apunta lo primero que comas</h2>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          No hace falta configurar nada para empezar. Elige cómo te resulte más cómodo:
        </p>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          {accesos.map(({ href, icon: Icon, label, hint }) => (
            <Link
              key={href}
              href={href}
              className="flex min-h-[5.5rem] flex-col items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--color-border-strong)] p-3 text-center hover:bg-[var(--color-surface-2)]"
            >
              <Icon size={22} aria-hidden="true" className="text-[var(--color-primary)]" />
              <span className="text-sm font-semibold">{label}</span>
              <span className="text-xs text-[var(--color-muted)]">{hint}</span>
            </Link>
          ))}
        </div>
      </div>
      <div className={`${CARD} flex flex-wrap items-center justify-between gap-3 p-4`}>
        <p className="min-w-0 flex-1 text-sm">
          <span className="font-semibold">¿Cuántas calorías te tocan?</span>{" "}
          <span className="text-[var(--color-muted)]">
            Cuatro datos y te lo calculo, con sus macros.
          </span>
        </p>
        <Link
          href="/bienvenida"
          className="inline-flex min-h-11 items-center rounded-full bg-[var(--color-primary)] px-4 text-sm font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)]"
        >
          Calcularlo
        </Link>
      </div>
    </section>
  );
}

export function TodayDashboard({ displayName }: { displayName: string }) {
  const userId = useCurrentUserId();
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waterNote, setWaterNote] = useState<string | null>(null);
  // Sube cada vez que se recargan los datos del día, para que la semana se entere de lo
  // que se acaba de apuntar sin tener que pasarle los datos.
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    const date = localDateIso();
    setReloadKey((n) => n + 1);
    try {
      const [log, targets, water, supplements, fasting] = await Promise.all([
        apiFetch<LogDay>(`/api/log?date=${date}`),
        apiFetch<TargetsResponse>("/api/calc/targets").catch((err) => {
          if (err instanceof ApiError && err.status === 422) return null; // perfil incompleto
          throw err;
        }),
        apiFetch<WaterDay>(`/api/water/log?date=${date}`).catch(() => null),
        apiFetch<SupplementsToday>("/api/supplements/today").catch(() => null),
        apiFetch<Fasting | null>("/api/fasting/current").catch(() => null),
      ]);
      setData({ log, targets, water, supplements, fasting });
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
    const reload = () => void load();
    window.addEventListener("myfood:queue-flushed", reload);
    window.addEventListener(DATA_CHANGED_EVENT, reload);
    const stop = onQueueChanged(reload);
    return () => {
      window.removeEventListener("myfood:queue-flushed", reload);
      window.removeEventListener(DATA_CHANGED_EVENT, reload);
      stop();
    };
  }, [load]);

  async function addWater(ml: number) {
    setWaterNote(null);
    try {
      const outcome = await submitOrQueue({
        userId: userId ?? "",
        kind: "water",
        label: `Agua — ${ml} ml (${localDateIso()})`,
        payload: { log_date: localDateIso(), ml },
      });
      setWaterNote(
        outcome.queued
          ? "Sin conexión: guardado en el dispositivo, se registrará al volver la red."
          : `Añadidos ${ml} ml.`,
      );
      if (!outcome.queued) await load();
    } catch (err) {
      setWaterNote(errorMessage(err));
    }
  }

  async function takeSupplement(supplementId: string, skipped: boolean) {
    try {
      await apiFetch(`/api/supplements/${supplementId}/log`, {
        method: "POST",
        body: JSON.stringify({ log_date: localDateIso(), skipped }),
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (error && !data) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!data) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton lines={2} />
        <Skeleton lines={5} />
      </div>
    );
  }

  const { log, targets, water, supplements, fasting } = data;
  const totals = log.totals;
  const meals = diaryMeals(log.food);
  const pendingDoses = (supplements?.doses ?? []).filter(
    (d) => d.status === "pending" || d.status === "overdue",
  );
  // Sin objetivos Y sin nada apuntado: no hay marcador que enseñar todavía. Con una de las
  // dos cosas sí lo hay — los totales del día valen aunque no haya objetivo contra el que
  // compararlos.
  const primerDia = !targets && log.food.length === 0;
  const longDate = new Date().toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  const today = longDate.charAt(0).toUpperCase() + longDate.slice(1);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-sm font-medium text-[var(--color-muted)]">{today}</p>
        <h1 className="text-3xl font-extrabold tracking-tight">Hola, {displayName}</h1>
      </div>

      {primerDia ? (
        <PrimerDia />
      ) : (
        <>
          {!targets && (
            <EmptyState
              message="Aún no tienes objetivos: dime qué quieres conseguir y los calculo en un minuto."
              actionLabel="Calcular mis calorías"
              actionHref="/bienvenida"
            />
          )}

      <section aria-label="Calorías y macros de hoy" className={`${CARD} p-5`}>
        <div className="flex items-center justify-between gap-4 sm:gap-8">
          <BudgetRing consumed={totals.kcal} target={targets?.kcal} className="h-32 w-32 sm:h-40 sm:w-40" />
          <dl className="grid w-full min-w-0 max-w-[16rem] gap-2.5 text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-muted)]">Objetivo</dt>
              <dd className="font-bold">{targets ? `${Math.round(targets.kcal)} kcal` : "—"}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-muted)]">Comida</dt>
              <dd className="font-bold">− {Math.round(totals.kcal)} kcal</dd>
            </div>
            <div className="flex items-baseline justify-between gap-3 border-t border-[var(--color-border)] pt-2.5">
              <dt className="font-semibold">Restantes</dt>
              <dd className="font-extrabold text-[var(--color-primary)]">
                {targets ? `${Math.max(0, Math.round(targets.kcal - totals.kcal))} kcal` : "—"}
              </dd>
            </div>
          </dl>
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          <MacroProgress label="Proteína" value={totals.protein_g} target={targets?.protein_g} color="var(--color-protein)" />
          <MacroProgress label="Carbohidratos" value={totals.carbs_g} target={targets?.carbs_g} color="var(--color-carbs)" />
          <MacroProgress label="Grasa" value={totals.fat_g} target={targets?.fat_g} color="var(--color-fat)" />
        </div>
      </section>

      <WeekBudget date={localDateIso()} reloadKey={reloadKey} />
        </>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {water && (
          <section aria-label="Agua de hoy" className="rounded-[var(--radius-card)] p-5" style={{ background: "var(--tint-sky)" }}>
            <div className="flex items-center gap-2 text-sm font-bold">
              <Droplets size={18} aria-hidden="true" className="text-[var(--color-water)]" /> Agua
            </div>
            <p className="mt-2 text-3xl font-extrabold tracking-tight">
              {Math.round(water.total_ml)}
              <span className="text-base font-semibold text-[var(--color-muted)]"> / {Math.round(water.target_ml)} ml</span>
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void addWater(200)}
                className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[var(--color-surface)] px-4 text-sm font-bold shadow-sm"
              >
                <Plus size={16} aria-hidden="true" /> Vaso (200 ml)
              </button>
              <Link href="/water" className="text-sm font-semibold text-[var(--color-muted)] underline">
                Más opciones
              </Link>
            </div>
            {waterNote && <p className="mt-2 text-xs text-[var(--color-muted)]">{waterNote}</p>}
          </section>
        )}

        <section aria-label="Suplementos pendientes" className={`${CARD} p-5`}>
          <h2 className="mb-2 text-sm font-bold">Suplementos de hoy</h2>
          {supplements && supplements.doses.length > 0 ? (
            pendingDoses.length === 0 ? (
              <p className="text-sm text-[var(--color-muted)]">Todo al día.</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {pendingDoses.map((d) => (
                  <li key={d.schedule_id} className="flex items-center justify-between gap-2">
                    <span>
                      <span className="mr-2 font-mono text-xs text-[var(--color-muted)]">{d.time_of_day}</span>
                      {d.supplement_name}
                    </span>
                    <button
                      type="button"
                      onClick={() => void takeSupplement(d.supplement_id, false)}
                      className="rounded-full bg-[var(--color-primary)] px-3.5 py-1 text-xs font-bold text-[var(--color-on-primary)]"
                    >
                      Tomada
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <p className="text-sm text-[var(--color-muted)]">
              No tienes tomas programadas hoy.{" "}
              <Link href="/supplements" className="font-semibold underline">
                Suplementos
              </Link>
            </p>
          )}
        </section>
      </div>

      {fasting && (
        <Link
          href="/ayuno"
          className="flex items-center gap-3 rounded-[var(--radius-card)] p-4 text-sm font-semibold"
          style={{ background: "var(--tint-lilac)" }}
        >
          <Timer size={20} aria-hidden="true" className="shrink-0 text-[var(--color-primary)]" />
          <span>
            Ayuno en curso: {Math.floor(fasting.elapsed_hours)} h de {fasting.target_hours} h
          </span>
          <span className="ml-auto text-[var(--color-muted)] underline">Ver temporizador</span>
        </Link>
      )}

      <section aria-label="Diario de hoy" className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-xl font-extrabold tracking-tight">Diario de hoy</h2>
          <Link href="/log" className="text-sm font-semibold text-[var(--color-primary)]">
            Ver y editar
          </Link>
        </div>
        {meals.map((meal) => (
          <div key={meal.mealType} className={`${CARD} overflow-hidden`}>
            <div className="flex items-center justify-between gap-3 px-4 py-3">
              <div>
                <h3 className="text-[15px] font-bold">{MEAL_TYPE_LABELS[meal.mealType]}</h3>
                <p className="text-xs text-[var(--color-muted)]">{Math.round(meal.kcal)} kcal</p>
              </div>
              <Link
                href={`/log?meal=${meal.mealType}#registrar`}
                aria-label={`Añadir a ${MEAL_TYPE_LABELS[meal.mealType].toLowerCase()}`}
                className="grid h-10 w-10 place-items-center rounded-full bg-[var(--color-primary-soft)] text-[var(--color-primary)] transition-colors hover:brightness-95"
              >
                <Plus size={20} strokeWidth={2.5} aria-hidden="true" />
              </Link>
            </div>
            {meal.entries.length > 0 && (
              <ul className="divide-y divide-[var(--color-border)] border-t border-[var(--color-border)]">
                {meal.entries.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{entryName(e)}</span>
                      <span className="text-xs text-[var(--color-muted)]">{e.grams} g</span>
                    </span>
                    <span className="shrink-0 text-xs font-semibold text-[var(--color-muted)]">{Math.round(e.kcal)} kcal</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
