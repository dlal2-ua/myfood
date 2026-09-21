"use client";

import { useCallback, useEffect, useState } from "react";
import { PushSubscribeButton } from "@/components/PushSubscribeButton";
import { apiFetch, errorMessage } from "@/lib/api";
import { MEAL_TYPES, MEAL_TYPE_LABELS } from "@/lib/types";
import type { MealType, NotificationRule, Supplement, SupplementList } from "@/lib/types";
import { Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

const DAY_LABELS = ["L", "M", "X", "J", "V", "S", "D"];
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

const KIND_LABELS: Record<string, string> = {
  water: "Agua",
  supplement: "Suplemento",
  meal: "Comida",
  weigh_in: "Pesarse",
};

function hhmm(value: string): string {
  return value.slice(0, 5);
}

function describe(rule: NotificationRule, supplements: Record<string, Supplement>): string {
  const s = rule.schedule as Record<string, unknown>;
  const days = s.days_of_week as number[] | undefined;
  const daysText =
    days && days.length < 7 ? ` · ${days.map((d) => DAY_LABELS[d - 1]).join(" ")}` : "";
  if (rule.kind === "water") return `${(s.times as string[]).join(", ")}`;
  if (rule.kind === "supplement") {
    const name = supplements[s.supplement_id as string]?.name;
    return `${s.time as string}${name ? ` · ${name}` : ""}${daysText}`;
  }
  if (rule.kind === "meal") {
    return `${s.time as string} · ${MEAL_TYPE_LABELS[s.meal_type as MealType] ?? s.meal_type}`;
  }
  return `${s.time as string}${daysText}`;
}

export default function RemindersPage() {
  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [supplements, setSupplements] = useState<Record<string, Supplement>>({});
  const [quietFrom, setQuietFrom] = useState("23:00");
  const [quietTo, setQuietTo] = useState("08:00");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [mealType, setMealType] = useState<MealType>("lunch");
  const [mealTime, setMealTime] = useState("14:00");
  const [weighTime, setWeighTime] = useState("08:00");
  const [weighDays, setWeighDays] = useState<number[]>([1, 2, 3, 4, 5, 6, 7]);
  const [waterTimes, setWaterTimes] = useState("10:00, 13:00, 16:00, 19:00");

  const load = useCallback(async () => {
    try {
      const [ruleList, quiet, supps] = await Promise.all([
        apiFetch<NotificationRule[]>("/api/notification-rules"),
        apiFetch<{ quiet_from: string; quiet_to: string }>("/api/notification-rules/quiet-hours"),
        apiFetch<SupplementList>("/api/supplements?include_inactive=true"),
      ]);
      setRules(ruleList);
      setQuietFrom(hhmm(quiet.quiet_from));
      setQuietTo(hhmm(quiet.quiet_to));
      setSupplements(Object.fromEntries(supps.items.map((s) => [s.id, s])));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setMessage(null);
    try {
      await action();
      if (done) setMessage(done);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const createRule = (kind: string, schedule: Record<string, unknown>) =>
    apiFetch("/api/notification-rules", {
      method: "POST",
      body: JSON.stringify({ kind, schedule }),
    });

  function addWater(e: React.FormEvent) {
    e.preventDefault();
    const times = waterTimes
      .split(/[,\s]+/)
      .map((t) => t.trim())
      .filter(Boolean);
    if (times.length === 0 || times.some((t) => !HHMM.test(t))) {
      setError("Escribe las horas como HH:MM separadas por comas, por ejemplo 10:00, 16:00.");
      return;
    }
    void run(() => createRule("water", { times }), "Recordatorio de agua creado.");
  }

  if (loading) return <Skeleton lines={3} />;

  return (
    <main className="flex max-w-2xl flex-col gap-8">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Recordatorios</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Los avisos son cortos y solo llegan si todavía tienen sentido: si ya has bebido tu agua,
          tomado el suplemento, registrado esa comida o pesado hoy, no se envían.
        </p>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {message && <p className="text-sm text-[var(--color-primary)]">{message}</p>}

      <section className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <h2 className="text-lg font-semibold">Notificaciones en este dispositivo</h2>
        <PushSubscribeButton />
      </section>

      <section className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <h2 className="text-lg font-semibold">No molestar</h2>
        <p className="text-sm text-neutral-500">
          Dentro de este tramo no se envía ningún aviso. Se aplica a todos tus recordatorios.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(
              () =>
                apiFetch("/api/notification-rules/quiet-hours", {
                  method: "PUT",
                  body: JSON.stringify({ quiet_from: quietFrom, quiet_to: quietTo }),
                }),
              "Horas de silencio guardadas.",
            );
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-1 text-sm">
            Desde
            <input type="time" className={inputClass} value={quietFrom} onChange={(e) => setQuietFrom(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Hasta
            <input type="time" className={inputClass} value={quietTo} onChange={(e) => setQuietTo(e.target.value)} />
          </label>
          <button type="submit" className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] font-semibold hover:bg-[var(--color-primary-hover)]">
            Guardar
          </button>
        </form>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Tus recordatorios</h2>
        {rules.length === 0 ? (
          <p className="text-sm text-neutral-500">Todavía no tienes ninguno.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-[var(--color-border)]">
            {rules.map((rule) => (
              <li key={rule.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                <span className={rule.is_enabled ? "" : "text-neutral-400"}>
                  <span className="font-medium">{KIND_LABELS[rule.kind] ?? rule.kind}</span>
                  <span className="ml-2 text-neutral-500">{describe(rule, supplements)}</span>
                </span>
                <span className="flex items-center gap-3">
                  <label className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={rule.is_enabled}
                      onChange={(e) =>
                        void run(() =>
                          apiFetch(`/api/notification-rules/${rule.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ is_enabled: e.target.checked }),
                          }),
                        )
                      }
                    />
                    Activo
                  </label>
                  <button
                    type="button"
                    className="text-neutral-500 underline"
                    onClick={() =>
                      void run(() => apiFetch(`/api/notification-rules/${rule.id}`, { method: "DELETE" }))
                    }
                  >
                    Eliminar
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-neutral-500">
          Los recordatorios de suplementos se crean al añadir el suplemento (casilla «Recordarme»).
        </p>
      </section>

      <section className="flex flex-col gap-4 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <h2 className="text-lg font-semibold">Añadir un recordatorio</h2>

        <form onSubmit={addWater} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-1 flex-col gap-1 text-sm">
            Agua (hasta 8 horas al día)
            <input className={inputClass} value={waterTimes} onChange={(e) => setWaterTimes(e.target.value)} />
          </label>
          <button type="submit" className="rounded-full border border-[var(--color-border-strong)] font-medium px-4 py-2 text-sm">
            Añadir
          </button>
        </form>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(
              () => createRule("meal", { time: mealTime, meal_type: mealType }),
              "Recordatorio de comida creado.",
            );
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-1 text-sm">
            Registrar comida
            <select className={inputClass} value={mealType} onChange={(e) => setMealType(e.target.value as MealType)}>
              {MEAL_TYPES.map((m) => (
                <option key={m} value={m}>
                  {MEAL_TYPE_LABELS[m]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Hora
            <input type="time" className={inputClass} value={mealTime} onChange={(e) => setMealTime(e.target.value)} />
          </label>
          <button type="submit" className="rounded-full border border-[var(--color-border-strong)] font-medium px-4 py-2 text-sm">
            Añadir
          </button>
        </form>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (weighDays.length === 0) {
              setError("Elige al menos un día.");
              return;
            }
            void run(
              () => createRule("weigh_in", { time: weighTime, days_of_week: weighDays }),
              "Recordatorio de peso creado.",
            );
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <label className="flex flex-col gap-1 text-sm">
            Pesarme
            <input type="time" className={inputClass} value={weighTime} onChange={(e) => setWeighTime(e.target.value)} />
          </label>
          <div role="group" aria-label="Días" className="flex gap-1">
            {DAY_LABELS.map((label, index) => {
              const day = index + 1;
              const on = weighDays.includes(day);
              return (
                <button
                  key={day}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    setWeighDays(on ? weighDays.filter((d) => d !== day) : [...weighDays, day].sort())
                  }
                  className={`h-9 w-9 rounded-full border text-sm ${
                    on
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-[var(--color-on-primary)]"
                      : "border-[var(--color-border-strong)]"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <button type="submit" className="rounded-full border border-[var(--color-border-strong)] font-medium px-4 py-2 text-sm">
            Añadir
          </button>
        </form>
      </section>
    </main>
  );
}
