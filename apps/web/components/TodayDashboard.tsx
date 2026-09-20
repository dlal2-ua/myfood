"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useCurrentUserId } from "@/components/CurrentUser";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { MacroBar } from "@/components/ui/MacroBar";
import { Ring } from "@/components/ui/Ring";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import { onQueueChanged, submitOrQueue } from "@/lib/offlineQueue";
import { entryName, groupByMeal } from "@/lib/today";
import { MEAL_TYPE_LABELS } from "@/lib/types";
import type {
  Fasting,
  LogDay,
  SupplementsToday,
  TargetsResponse,
  WaterDay,
} from "@/lib/types";

interface TodayData {
  log: LogDay;
  targets: TargetsResponse | null;
  water: WaterDay | null;
  supplements: SupplementsToday | null;
  fasting: Fasting | null;
}

/** Pantalla «Hoy» (sección 14.1): anillos de kcal y macros, agua, suplementos pendientes, ayuno y
 * las comidas del día, con un botón flotante para añadir. Los objetivos son orientativos y no
 * se colorean como «bien» o «mal» (R10). */
export function TodayDashboard({ displayName }: { displayName: string }) {
  const userId = useCurrentUserId();
  const [data, setData] = useState<TodayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [waterNote, setWaterNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const date = localDateIso();
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
    const onFlushed = () => void load();
    window.addEventListener("myfood:queue-flushed", onFlushed);
    const stop = onQueueChanged(() => void load());
    return () => {
      window.removeEventListener("myfood:queue-flushed", onFlushed);
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
    setSheetOpen(false);
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
  const meals = groupByMeal(log.food);
  const pendingDoses = (supplements?.doses ?? []).filter(
    (d) => d.status === "pending" || d.status === "overdue",
  );

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">Hola, {displayName}</h1>
        <p className="text-sm text-neutral-500">Tu día de hoy, {localDateIso()}.</p>
      </div>

      {!targets && (
        <EmptyState
          message="Completa tu perfil (sexo, fecha de nacimiento, altura) y registra tu peso para ver tus objetivos de hoy."
          actionLabel="Completar perfil"
          actionHref="/profile"
        />
      )}

      <section aria-label="Calorías y macros de hoy" className="rounded-[var(--radius-card)] border border-neutral-200 p-4 dark:border-neutral-800">
        <div className="grid grid-cols-2 justify-items-center gap-4 sm:grid-cols-4">
          <Ring value={totals.kcal} target={targets?.kcal} color="var(--color-primary)" label="Energía" unit="kcal" />
          <Ring value={totals.protein_g} target={targets?.protein_g} color="var(--color-protein)" label="Proteína" unit="g" />
          <Ring value={totals.fat_g} target={targets?.fat_g} color="var(--color-fat)" label="Grasa" unit="g" />
          <Ring value={totals.carbs_g} target={targets?.carbs_g} color="var(--color-carbs)" label="Carbohidratos" unit="g" />
        </div>
        <div className="mt-4">
          <MacroBar
            slices={[
              { key: "p", label: "Proteína", grams: totals.protein_g, color: "var(--color-protein)" },
              { key: "f", label: "Grasa", grams: totals.fat_g, color: "var(--color-fat)" },
              { key: "c", label: "Carbohidratos", grams: totals.carbs_g, color: "var(--color-carbs)" },
            ]}
          />
        </div>
      </section>

      <div className="grid gap-4 sm:grid-cols-2">
        {water && (
          <section aria-label="Agua de hoy" className="rounded-[var(--radius-card)] border border-neutral-200 p-4 dark:border-neutral-800">
            <div className="flex items-center gap-4">
              <Ring value={water.total_ml} target={water.target_ml} color="var(--color-water)" label="Agua" unit="ml" size={80} />
              <div className="flex flex-col gap-2 text-sm">
                <button
                  type="button"
                  onClick={() => void addWater(200)}
                  className="rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700"
                >
                  + Vaso (200 ml)
                </button>
                <Link href="/water" className="text-neutral-500 underline">
                  Más opciones
                </Link>
              </div>
            </div>
            {waterNote && <p className="mt-2 text-xs text-neutral-500">{waterNote}</p>}
          </section>
        )}

        <section aria-label="Suplementos pendientes" className="rounded-[var(--radius-card)] border border-neutral-200 p-4 dark:border-neutral-800">
          <h2 className="mb-2 text-sm font-semibold text-neutral-500">Suplementos de hoy</h2>
          {supplements && supplements.doses.length > 0 ? (
            pendingDoses.length === 0 ? (
              <p className="text-sm">Todo al día.</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {pendingDoses.map((d) => (
                  <li key={d.schedule_id} className="flex items-center justify-between gap-2">
                    <span>
                      <span className="mr-2 font-mono">{d.time_of_day}</span>
                      {d.supplement_name}
                    </span>
                    <button
                      type="button"
                      onClick={() => void takeSupplement(d.supplement_id, false)}
                      className="rounded-lg bg-[var(--color-primary)] px-3 py-1 text-xs text-white"
                    >
                      Tomada
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <p className="text-sm text-neutral-500">
              No tienes tomas programadas hoy.{" "}
              <Link href="/supplements" className="underline">
                Suplementos
              </Link>
            </p>
          )}
        </section>
      </div>

      {fasting && (
        <p className="rounded-[var(--radius-card)] border border-neutral-200 p-3 text-sm dark:border-neutral-800">
          Ayuno en curso: {Math.floor(fasting.elapsed_hours)} h de {fasting.target_hours} h.{" "}
          <Link href="/ayuno" className="underline">
            Ver temporizador
          </Link>
        </p>
      )}

      <section aria-label="Comidas de hoy">
        <h2 className="mb-2 text-lg font-semibold">Comidas de hoy</h2>
        {meals.length === 0 ? (
          <EmptyState
            message="Todavía no has registrado nada hoy."
            actionLabel="Registrar la primera comida"
            actionHref="/scan"
          />
        ) : (
          <div className="flex flex-col gap-4">
            {meals.map((group) => (
              <div key={group.mealType}>
                <h3 className="mb-1 text-sm font-semibold text-neutral-500">
                  {MEAL_TYPE_LABELS[group.mealType]}
                </h3>
                <ul className="divide-y divide-neutral-200 rounded-[var(--radius-card)] border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
                  {group.entries.map((e) => (
                    <li key={e.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                      <span>
                        {entryName(e)}
                        <span className="ml-2 text-xs text-neutral-500">{e.grams} g</span>
                      </span>
                      <span className="text-xs text-neutral-500">{Math.round(e.kcal)} kcal</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <Link href="/log" className="text-sm text-neutral-500 underline">
              Ver y editar el registro del día
            </Link>
          </div>
        )}
      </section>

      <button
        type="button"
        onClick={() => setSheetOpen(true)}
        aria-label="Añadir"
        className="fixed bottom-[max(1.25rem,env(safe-area-inset-bottom))] right-5 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-primary)] text-3xl text-white shadow-lg"
      >
        <span aria-hidden="true">+</span>
      </button>

      <BottomSheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Añadir">
        <ul className="flex flex-col gap-2 text-base">
          {[
            { href: "/scan", label: "Escanear un producto" },
            { href: "/foods", label: "Buscar un alimento" },
            { href: "/log", label: "Registrar con lenguaje natural" },
            { href: "/chat", label: "Hablar con el chat" },
          ].map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="flex min-h-11 items-center rounded-[var(--radius-control)] border border-neutral-200 px-3 dark:border-neutral-800"
                onClick={() => setSheetOpen(false)}
              >
                {item.label}
              </Link>
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={() => void addWater(200)}
              className="flex min-h-11 w-full items-center rounded-[var(--radius-control)] border border-neutral-200 px-3 text-left dark:border-neutral-800"
            >
              Beber un vaso de agua
            </button>
          </li>
        </ul>
      </BottomSheet>
    </div>
  );
}
