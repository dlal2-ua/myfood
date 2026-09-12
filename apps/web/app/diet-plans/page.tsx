"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { DietPlan } from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function DietPlansPage() {
  const [plans, setPlans] = useState<DietPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("Plan semanal");
  const [startDate, setStartDate] = useState(todayIso());
  const [numDays, setNumDays] = useState("7");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setPlans(await apiFetch<DietPlan[]>("/api/diet-plans"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onGenerate(e: React.FormEvent) {
    e.preventDefault();
    setGenerating(true);
    setGenerateError(null);
    try {
      await apiFetch("/api/diet-plans/generate", {
        method: "POST",
        body: JSON.stringify({
          name,
          start_date: startDate,
          num_days: Number(numDays),
        }),
      });
      await load();
    } catch (err) {
      setGenerateError(errorMessage(err));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Planes de dieta</h1>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Generar un plan nuevo</h2>
        <form onSubmit={onGenerate} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Nombre
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Fecha de inicio
            <input
              type="date"
              className={inputClass}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Días
            <input
              type="number"
              min={1}
              max={14}
              className={inputClass}
              value={numDays}
              onChange={(e) => setNumDays(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={generating}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
          >
            {generating ? "Generando…" : "Generar plan"}
          </button>
        </form>
        {generateError && <p className="mt-2 text-sm text-red-600">{generateError}</p>}
        <p className="mt-2 text-sm text-neutral-500">
          Necesitas el perfil completo (sexo, fecha de nacimiento, altura) y al menos un peso
          registrado en Medidas.
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Tus planes</h2>
        {loading && <p className="text-sm text-neutral-500">Cargando…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && plans.length === 0 && (
          <p className="text-sm text-neutral-500">Todavía no has generado ningún plan.</p>
        )}
        <ul className="flex flex-col gap-2">
          {plans.map((plan) => (
            <li key={plan.id}>
              <Link
                href={`/diet-plans/${plan.id}`}
                className="block rounded-lg border border-neutral-200 p-3 hover:border-[var(--color-primary)] dark:border-neutral-800"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{plan.name}</span>
                  <span className="text-xs uppercase text-neutral-500">{plan.status}</span>
                </div>
                <p className="text-sm text-neutral-500">
                  {plan.start_date}
                  {plan.end_date ? ` – ${plan.end_date}` : ""} · {plan.target_kcal} kcal/día
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
