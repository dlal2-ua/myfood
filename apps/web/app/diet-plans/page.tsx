"use client";

import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { AiProposal, AiSession, DietPlan, FoodDetail } from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

const MAX_POLL_ATTEMPTS = 60; // 60 × 2s = 120s (sección 10.6)
const POLL_INTERVAL_MS = 2000;

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

  const [aiConsent, setAiConsent] = useState(false);
  const [aiNumDays, setAiNumDays] = useState("7");
  const [aiRequesting, setAiRequesting] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiSession, setAiSession] = useState<AiSession | null>(null);
  const [aiProposals, setAiProposals] = useState<AiProposal[]>([]);
  const [foodNames, setFoodNames] = useState<Record<string, string>>({});
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const pollCountRef = useRef(0);

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

  async function loadPendingProposals() {
    const proposals = await apiFetch<AiProposal[]>("/api/ai/proposals?status=pending");
    setAiProposals(proposals);

    const missingIds = new Set<string>();
    for (const proposal of proposals) {
      for (const meal of proposal.payload.meals) {
        for (const item of meal.items) {
          if (!(item.food_id in foodNames)) missingIds.add(item.food_id);
        }
      }
    }
    if (missingIds.size > 0) {
      const entries = await Promise.all(
        [...missingIds].map(async (id) => {
          try {
            const food = await apiFetch<FoodDetail>(`/api/foods/${id}`);
            return [id, food.name_es] as const;
          } catch {
            return [id, "Alimento"] as const;
          }
        }),
      );
      setFoodNames((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
    }
  }

  async function pollAiSession(sessionId: string) {
    pollCountRef.current = 0;
    const tick = async () => {
      pollCountRef.current += 1;
      let session: AiSession;
      try {
        session = await apiFetch<AiSession>(`/api/ai/sessions/${sessionId}`);
      } catch (err) {
        setAiError(errorMessage(err));
        return;
      }
      setAiSession(session);
      if (session.status === "running") {
        if (pollCountRef.current >= MAX_POLL_ATTEMPTS) {
          setAiError("La generación está tardando más de lo esperado. Vuelve a intentarlo.");
          return;
        }
        setTimeout(() => void tick(), POLL_INTERVAL_MS);
        return;
      }
      if (session.status === "succeeded") {
        await loadPendingProposals();
      }
    };
    await tick();
  }

  async function onGenerateWithAi(e: React.FormEvent) {
    e.preventDefault();
    setAiRequesting(true);
    setAiError(null);
    setAiSession(null);
    try {
      if (aiConsent) {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: "ai_processing", version: "v1" }),
        });
      }
      const session = await apiFetch<AiSession>("/api/ai/diet-plan", {
        method: "POST",
        body: JSON.stringify({ num_days: Number(aiNumDays) }),
      });
      setAiSession(session);
      await pollAiSession(session.id);
    } catch (err) {
      setAiError(errorMessage(err));
    } finally {
      setAiRequesting(false);
    }
  }

  async function decideProposal(proposalId: string, decision: "approve" | "reject") {
    setDecidingId(proposalId);
    setAiError(null);
    try {
      await apiFetch(`/api/ai/proposals/${proposalId}/${decision}`, { method: "POST" });
      setAiProposals((prev) => prev.filter((p) => p.id !== proposalId));
      if (decision === "approve") {
        await load();
      }
    } catch (err) {
      setAiError(errorMessage(err));
    } finally {
      setDecidingId(null);
    }
  }

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Planes de dieta</h1>
      <MedicalDisclaimer />

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

      <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="mb-3 text-lg font-semibold">Generar con IA (iafood)</h2>
        <p className="mb-3 text-sm text-neutral-500">
          Claude propone la estructura de comidas (nunca gramos ni calorías) a partir de tu
          objetivo y tus restricciones; el motor determinista de MyFood calcula las cantidades
          exactas. Nada se aplica hasta que apruebes cada día.
        </p>
        <form onSubmit={onGenerateWithAi} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Días
            <input
              type="number"
              min={1}
              max={7}
              className={inputClass}
              value={aiNumDays}
              onChange={(e) => setAiNumDays(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={aiRequesting || aiSession?.status === "running"}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
          >
            {aiRequesting || aiSession?.status === "running" ? "Generando…" : "Generar con IA"}
          </button>
        </form>
        <label className="mt-2 flex items-start gap-2 text-sm text-neutral-600 dark:text-neutral-400">
          <input
            type="checkbox"
            checked={aiConsent}
            onChange={(e) => setAiConsent(e.target.checked)}
            className="mt-0.5"
          />
          Acepto que mis objetivos y restricciones (anonimizados, sin nombre ni datos
          identificativos) se envíen a Claude para diseñar la estructura del plan.
        </label>

        {aiError && <p className="mt-2 text-sm text-red-600">{aiError}</p>}

        {aiSession?.status === "rejected_validation" && (
          <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950">
            <p className="font-medium">No se pudo generar un plan válido.</p>
            <ul className="mt-1 list-disc pl-5">
              {aiSession.validation_errors?.map((e, i) => <li key={i}>{e.message}</li>)}
            </ul>
          </div>
        )}
        {aiSession?.status === "failed" && (
          <p className="mt-3 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
            {aiSession.validation_errors?.[0]?.message ?? "La generación falló."}
          </p>
        )}

        {aiProposals.length > 0 && (
          <div className="mt-4 flex flex-col gap-3">
            <h3 className="font-medium">Propuestas pendientes de aprobar</h3>
            {aiProposals
              .sort((a, b) => a.payload.day_index - b.payload.day_index)
              .map((proposal) => (
                <div
                  key={proposal.id}
                  className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
                >
                  <p className="font-medium">Día {proposal.payload.day_index + 1}</p>
                  {proposal.rationale && (
                    <p className="mt-1 text-sm text-neutral-500">{proposal.rationale}</p>
                  )}
                  <ul className="mt-2 flex flex-col gap-1 text-sm">
                    {proposal.payload.meals.map((meal, mi) => (
                      <li key={mi}>
                        <span className="font-medium">{meal.meal_type}:</span>{" "}
                        {meal.items
                          .map(
                            (item) =>
                              `${foodNames[item.food_id] ?? "…"} (${Math.round(item.grams)} g)`,
                          )
                          .join(", ")}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      disabled={decidingId === proposal.id}
                      onClick={() => void decideProposal(proposal.id, "approve")}
                      className="rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-sm text-white disabled:opacity-60"
                    >
                      Aprobar
                    </button>
                    <button
                      type="button"
                      disabled={decidingId === proposal.id}
                      onClick={() => void decideProposal(proposal.id, "reject")}
                      className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-60 dark:border-neutral-700"
                    >
                      Rechazar
                    </button>
                  </div>
                </div>
              ))}
          </div>
        )}
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
