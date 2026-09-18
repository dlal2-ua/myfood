"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { GamificationSummary, HeatmapDay } from "@/lib/types";

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

export default function ProgressPage() {
  const [data, setData] = useState<GamificationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<GamificationSummary>("/api/gamification/summary")
      .then(setData)
      .catch((err) => setError(errorMessage(err)));
  }, []);

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-4 py-8">
      <div>
        <h1 className="text-xl font-semibold">Progreso</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Premia el registro constante, nunca el déficit calórico ni el resultado corporal.
        </p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

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
                      : "border-neutral-200 dark:border-neutral-800"
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
