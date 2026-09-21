"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { DailyBarsChart, WeightTrendChart } from "@/components/charts";
import type { GamificationSummary, HeatmapDay, ProgressSummary, TdeeHistory } from "@/lib/types";

const PERIODS = [
  { value: "7d", label: "7 días" },
  { value: "30d", label: "30 días" },
  { value: "90d", label: "3 meses" },
  { value: "365d", label: "1 año" },
];

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
      <p className="text-xl font-semibold">{value}</p>
      <p className="text-xs text-neutral-500">{label}</p>
      {hint && <p className="mt-1 text-xs text-neutral-400">{hint}</p>}
    </div>
  );
}

function signed(value: number, digits = 1): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/** Verde neutro por intensidad de registro — nunca rojo, nunca ligado a si
 * se cumplió el objetivo calórico (R10, documento 2 sección 23). Colorea
 * "hubo actividad", no "resultado". */
function heatmapColor(count: number): string {
  if (count === 0) return "var(--heatmap-0, #e5e7eb)";
  if (count === 1) return "#bbf7d0";
  if (count === 2) return "#4ade80";
  return "#16a34a";
}

function Heatmap({ days }: { days: HeatmapDay[] }) {
  // Semanas como columnas, lunes-domingo como filas — mismo criterio
  // visual que un heatmap de contribuciones estilo GitHub.
  const weeks: HeatmapDay[][] = [];
  let current: HeatmapDay[] = [];
  for (const day of days) {
    const weekday = new Date(day.date).getUTCDay(); // 0 = domingo
    if (current.length === 0 && weekday !== 1) {
      current.push(...Array(weekday === 0 ? 6 : weekday - 1).fill(null));
    }
    current.push(day);
    if (current.length === 7) {
      weeks.push(current);
      current = [];
    }
  }
  if (current.length > 0) weeks.push(current);

  return (
    <div className="overflow-x-auto">
      <div className="flex gap-[3px]" style={{ width: "fit-content" }}>
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-[3px]">
            {week.map((day, di) =>
              day ? (
                <div
                  key={di}
                  title={`${day.date}: ${day.count} registro(s)`}
                  className="h-[11px] w-[11px] rounded-sm"
                  style={{ backgroundColor: heatmapColor(day.count) }}
                />
              ) : (
                <div key={di} className="h-[11px] w-[11px]" />
              ),
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Trends() {
  const [period, setPeriod] = useState("30d");
  const [summary, setSummary] = useState<ProgressSummary | null>(null);
  const [tdee, setTdee] = useState<TdeeHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ProgressSummary>(`/api/progress/summary?period=${period}`)
      .then((res) => {
        setSummary(res);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }, [period]);

  useEffect(() => {
    apiFetch<TdeeHistory>("/api/progress/tdee")
      .then(setTdee)
      .catch(() => setTdee(null));
  }, []);

  const weight = summary?.weight;
  const intake = summary?.intake;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-neutral-500">Tendencias</h2>
        <div role="group" aria-label="Periodo" className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              aria-pressed={period === p.value}
              onClick={() => setPeriod(p.value)}
              className={`rounded-full border px-3 py-1 text-xs ${
                period === p.value
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-[var(--color-on-primary)]"
                  : "border-[var(--color-border-strong)]"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {summary && weight && intake && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat
              label="Cambio de peso"
              value={weight.change_kg != null ? `${signed(weight.change_kg)} kg` : "—"}
              hint={weight.end_kg != null ? `Ahora ${weight.end_kg} kg` : undefined}
            />
            <Stat
              label="Tendencia"
              value={
                weight.trend_kg_per_week != null
                  ? `${signed(weight.trend_kg_per_week, 2)} kg/sem`
                  : "—"
              }
              hint={weight.trend_kg_per_week == null ? "Hace falta una semana de pesadas" : undefined}
            />
            <Stat
              label="Días con registro"
              value={`${intake.logging_days}/${summary.period_days}`}
              hint={`${intake.adherence_pct.toFixed(0)} % de los días`}
            />
            <Stat
              label="Calorías medias"
              value={intake.avg_kcal != null ? `${Math.round(intake.avg_kcal)} kcal` : "—"}
              hint={
                intake.target_kcal != null ? `Tu objetivo: ${Math.round(intake.target_kcal)} kcal` : undefined
              }
            />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold text-neutral-500">Peso</h3>
            <WeightTrendChart
              data={weight.points.map((p) => ({
                date: p.date,
                weight: p.weight_kg,
                average: p.ma7_kg,
              }))}
            />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold text-neutral-500">Calorías por día</h3>
            <DailyBarsChart
              data={intake.daily.map((d) => ({ date: d.date, value: d.kcal }))}
              reference={intake.target_kcal}
              unit=" kcal"
            />
          </div>
          {intake.avg_protein_g != null && (
            <p className="text-xs text-neutral-500">
              Media por día registrado: {Math.round(intake.avg_protein_g)} g de proteína ·{" "}
              {Math.round(intake.avg_fat_g ?? 0)} g de grasa · {Math.round(intake.avg_carbs_g ?? 0)} g
              de carbohidratos
              {summary.water_avg_ml != null && ` · ${Math.round(summary.water_avg_ml)} ml de agua`}.
            </p>
          )}
        </>
      )}
      {tdee && tdee.current && (
        <div className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3 text-sm">
          <h3 className="mb-1 text-xs font-semibold text-neutral-500">
            Gasto energético estimado (TDEE adaptativo)
          </h3>
          <p>
            <span className="text-xl font-semibold">
              {Math.round(tdee.current.estimated_tdee)} kcal
            </span>{" "}
            <span className="text-neutral-500">
              a partir de {tdee.current.logging_days} días con registro y tu tendencia de peso.
            </span>
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            {tdee.source === "adaptive_tdee"
              ? "Tus objetivos ya parten de esta estimación en lugar de la fórmula."
              : "Todavía no es fiable (hacen falta 14 días de historial y 10 con comidas registradas): tus objetivos siguen usando la fórmula."}
          </p>
          {tdee.history.length > 1 && (
            <details className="mt-2 text-xs">
              <summary className="cursor-pointer">Historial semanal</summary>
              <table className="mt-1 w-full">
                <thead>
                  <tr className="text-left text-neutral-500">
                    <th>Semana</th>
                    <th>TDEE</th>
                    <th>Ingesta media</th>
                    <th>Fiable</th>
                  </tr>
                </thead>
                <tbody>
                  {tdee.history.map((row) => (
                    <tr key={row.week_start}>
                      <td>{row.week_start}</td>
                      <td>{Math.round(row.estimated_tdee)}</td>
                      <td>{Math.round(row.avg_intake_kcal)}</td>
                      <td>{row.is_reliable ? "sí" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

export default function ProgressPage() {
  const [data, setData] = useState<GamificationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<GamificationSummary>("/api/gamification/summary")
      .then(setData)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  return (
    <main className="flex max-w-2xl flex-col gap-8">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Progreso</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Premia el registro constante, nunca el déficit calórico ni el resultado corporal.
        </p>
      </div>

      <Trends />

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {data && (
        <>
          <section className="flex gap-8">
            <div>
              <p className="text-2xl font-semibold">{data.current_streak}</p>
              <p className="text-sm text-neutral-500">días seguidos registrando</p>
            </div>
            <div>
              <p className="text-2xl font-semibold">{data.longest_streak}</p>
              <p className="text-sm text-neutral-500">racha más larga</p>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-neutral-500">
              Último año de registro
            </h2>
            <Heatmap days={data.heatmap} />
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-neutral-500">Logros</h2>
            <ul className="flex flex-col gap-3">
              {data.achievements.map((a) => (
                <li
                  key={a.key}
                  className={`rounded-lg border p-3 text-sm ${
                    a.earned
                      ? "border-green-300 bg-green-50 dark:border-green-900 dark:bg-green-950/30"
                      : "border-[var(--color-border)]"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {a.earned ? "✓ " : ""}
                      {a.title}
                    </span>
                    <span className="text-xs text-neutral-500">
                      {a.progress}/{a.target}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-neutral-500">{a.description}</p>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </main>
  );
}
