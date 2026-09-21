"use client";

import { localDateIso } from "@/lib/dates";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { BmrResponse, Measurement, Profile, TargetsResponse } from "@/lib/types";
import { Check } from "lucide-react";
import { BarChart } from "@/components/charts";
import { WeightTrend } from "@/components/WeightTrend";
import { RestrictionsPanel } from "@/components/RestrictionsPanel";
import {
  BMR_FORMULAS,
  formulaInfo,
  isUnavailable,
  recommendationReason,
  recommendedFormula,
  type BmrFormulaKey,
} from "@/lib/bmrFormulas";

const ACTIVITY_LEVELS: { value: Profile["activity_level"]; label: string }[] = [
  { value: "sedentary", label: "Sedentario" },
  { value: "light", label: "Ligero (1-3 días/semana)" },
  { value: "moderate", label: "Moderado (3-5 días/semana)" },
  { value: "active", label: "Activo (6-7 días/semana)" },
  { value: "very_active", label: "Muy activo (trabajo físico o 2x/día)" },
];

const GOALS: { value: Profile["goal"]; label: string }[] = [
  { value: "lose", label: "Perder peso" },
  { value: "maintain", label: "Mantener" },
  { value: "gain", label: "Ganar peso" },
];

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

/** Qué hace la fórmula elegida, y cuál sería la más ajustada con los datos registrados.
 * El selector ofrece cuatro nombres propios que no dicen nada por sí solos; sin esto, elegir
 * una u otra era adivinar. */
function BmrFormulaHelp({
  selected,
  hasBodyFatPct,
}: {
  selected: BmrFormulaKey;
  hasBodyFatPct: boolean;
}) {
  const info = formulaInfo(selected);
  const recommended = recommendedFormula(hasBodyFatPct);
  const isRecommended = selected === recommended;
  const unavailable = isUnavailable(selected, hasBodyFatPct);
  return (
    <div className="rounded-[var(--radius-card)] bg-[var(--color-surface-2)] p-3 text-xs leading-relaxed">
      <p className="flex flex-wrap items-center gap-1.5 font-bold">
        {info.label}
        {isRecommended && (
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-primary-soft)] px-2 py-0.5 text-[11px] text-[var(--color-primary)]">
            <Check size={11} aria-hidden="true" /> Recomendada para ti
          </span>
        )}
      </p>
      <p className="mt-1 text-[var(--color-muted)]">{info.description}</p>
      <p className="mt-1 text-[var(--color-muted)]">Necesita: {info.needs}</p>
      {unavailable ? (
        <p className="mt-1.5 font-semibold text-amber-700 dark:text-amber-300">
          Todavía no puedes usarla: registra tu %grasa corporal en Medidas, aquí abajo.
        </p>
      ) : !isRecommended ? (
        <p className="mt-1.5 font-semibold text-[var(--color-primary)]">
          Para ti sería más precisa {formulaInfo(recommended).label}:{" "}
          <span className="font-normal text-[var(--color-muted)]">
            {recommendationReason(hasBodyFatPct)}
          </span>
        </p>
      ) : (
        <p className="mt-1.5 text-[var(--color-muted)]">{recommendationReason(hasBodyFatPct)}</p>
      )}
    </div>
  );
}

function todayIso(): string {
  return localDateIso();
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSaved, setProfileSaved] = useState(false);

  const [measurements, setMeasurements] = useState<Measurement[]>([]);
  const [measuredOn, setMeasuredOn] = useState(todayIso());
  const [weightKg, setWeightKg] = useState("");
  const [bodyFatPct, setBodyFatPct] = useState("");
  const [measurementSaving, setMeasurementSaving] = useState(false);
  const [measurementError, setMeasurementError] = useState<string | null>(null);

  const [bmr, setBmr] = useState<BmrResponse | null>(null);
  const [targets, setTargets] = useState<TargetsResponse | null>(null);
  const [calcLoading, setCalcLoading] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);

  useEffect(() => {
    void loadProfile();
    void loadMeasurements();
  }, []);

  async function loadProfile() {
    setProfileLoading(true);
    try {
      const data = await apiFetch<Profile>("/api/profile");
      setProfile(data);
    } catch (err) {
      setProfileError(errorMessage(err));
    } finally {
      setProfileLoading(false);
    }
  }

  async function loadMeasurements() {
    try {
      const data = await apiFetch<Measurement[]>("/api/measurements");
      setMeasurements(data);
    } catch {
      // non-fatal: the weight chart just stays empty
    }
  }

  function updateProfileField<K extends keyof Profile>(key: K, value: Profile[K]) {
    setProfile((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  async function onSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setProfileSaving(true);
    setProfileError(null);
    setProfileSaved(false);
    try {
      const updated = await apiFetch<Profile>("/api/profile", {
        method: "PUT",
        body: JSON.stringify(profile),
      });
      setProfile(updated);
      setProfileSaved(true);
    } catch (err) {
      setProfileError(errorMessage(err));
    } finally {
      setProfileSaving(false);
    }
  }

  async function onSaveMeasurement(e: React.FormEvent) {
    e.preventDefault();
    setMeasurementSaving(true);
    setMeasurementError(null);
    try {
      await apiFetch("/api/measurements", {
        method: "POST",
        body: JSON.stringify({
          measured_on: measuredOn,
          weight_kg: weightKg ? Number(weightKg) : null,
          body_fat_pct: bodyFatPct ? Number(bodyFatPct) : null,
          source: "manual",
        }),
      });
      setWeightKg("");
      setBodyFatPct("");
      await loadMeasurements();
    } catch (err) {
      setMeasurementError(errorMessage(err));
    } finally {
      setMeasurementSaving(false);
    }
  }

  async function onCalculate() {
    setCalcLoading(true);
    setCalcError(null);
    setBmr(null);
    setTargets(null);
    try {
      const [bmrResult, targetsResult] = await Promise.all([
        apiFetch<BmrResponse>("/api/calc/bmr", { method: "POST", body: JSON.stringify({}) }),
        apiFetch<TargetsResponse>("/api/calc/targets"),
      ]);
      setBmr(bmrResult);
      setTargets(targetsResult);
    } catch (err) {
      setCalcError(errorMessage(err));
    } finally {
      setCalcLoading(false);
    }
  }

  // El %grasa decide qué fórmula de BMR es la más fiable: con él se puede calcular sobre la
  // masa magra. Vale cualquier medida registrada, no solo la última: el API usa la más
  // reciente que lo tenga.
  const hasBodyFatPct = measurements.some((m) => m.body_fat_pct != null);
  const recommended = recommendedFormula(hasBodyFatPct);

  const weightSeries = measurements
    .filter((m) => m.weight_kg != null)
    .map((m) => ({ date: m.measured_on, weightKg: Number(m.weight_kg) }));

  const macroData = targets
    ? [
        { label: "Proteína", value: targets.protein_g, color: "#2563eb" },
        { label: "Grasa", value: targets.fat_g, color: "#eab308" },
        { label: "Carbos", value: targets.carbs_g, color: "#16a34a" },
      ]
    : [];

  if (profileLoading) {
    return <p className="text-sm text-neutral-500">Cargando perfil…</p>;
  }

  if (!profile) {
    return <p className="text-sm text-red-600 dark:text-red-400">{profileError ?? "No se pudo cargar el perfil."}</p>;
  }

  return (
    <main className="flex flex-col gap-10 pb-16">
      <section>
        <h1 className="mb-4 text-3xl font-extrabold tracking-tight">Perfil</h1>
        <form onSubmit={onSaveProfile} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            Sexo
            <select
              className={inputClass}
              value={profile.sex ?? ""}
              onChange={(e) => updateProfileField("sex", (e.target.value || null) as Profile["sex"])}
            >
              <option value="">— Sin especificar —</option>
              <option value="male">Hombre</option>
              <option value="female">Mujer</option>
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Fecha de nacimiento
            <input
              type="date"
              className={inputClass}
              value={profile.birth_date ?? ""}
              onChange={(e) => updateProfileField("birth_date", e.target.value || null)}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Altura (cm)
            <input
              type="number"
              step="0.1"
              className={inputClass}
              value={profile.height_cm ?? ""}
              onChange={(e) =>
                updateProfileField("height_cm", e.target.value ? Number(e.target.value) : null)
              }
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Nivel de actividad
            <select
              className={inputClass}
              value={profile.activity_level}
              onChange={(e) =>
                updateProfileField("activity_level", e.target.value as Profile["activity_level"])
              }
            >
              {ACTIVITY_LEVELS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Objetivo
            <select
              className={inputClass}
              value={profile.goal}
              onChange={(e) => updateProfileField("goal", e.target.value as Profile["goal"])}
            >
              {GOALS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <div className="flex flex-col gap-1 text-sm sm:col-span-2">
            <label className="flex flex-col gap-1">
              Fórmula de BMR
              <select
                className={inputClass}
                value={profile.bmr_formula}
                onChange={(e) =>
                  updateProfileField("bmr_formula", e.target.value as Profile["bmr_formula"])
                }
              >
                {BMR_FORMULAS.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                    {o.key === recommended ? " — recomendada para ti" : ""}
                    {isUnavailable(o.key, hasBodyFatPct) ? " (necesita tu %grasa)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <BmrFormulaHelp
              selected={profile.bmr_formula as BmrFormulaKey}
              hasBodyFatPct={hasBodyFatPct}
            />
          </div>

          <label className="flex flex-col gap-1 text-sm">
            Comidas al día
            <input
              type="number"
              min={1}
              max={8}
              className={inputClass}
              value={profile.meals_per_day}
              onChange={(e) => updateProfileField("meals_per_day", Number(e.target.value))}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Ritmo de cambio (kg/semana)
            <input
              type="number"
              step="0.1"
              min={0}
              max={1.5}
              className={inputClass}
              value={profile.goal_rate_kg_week ?? ""}
              onChange={(e) =>
                updateProfileField(
                  "goal_rate_kg_week",
                  e.target.value ? Number(e.target.value) : null,
                )
              }
            />
          </label>

          <fieldset className="flex flex-col gap-2 text-sm sm:col-span-2">
            <legend className="mb-1 font-medium">Situación de salud (opcional)</legend>
            <p className="text-xs text-neutral-500">
              Si marcas alguna casilla, MyFood no te sugerirá suplementos con IA y te recomendará
              consultar a un profesional. Se guarda cifrado.
            </p>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={profile.is_pregnant_or_nursing}
                onChange={(e) => updateProfileField("is_pregnant_or_nursing", e.target.checked)}
              />
              Estoy embarazada o en periodo de lactancia
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={profile.has_medical_condition}
                onChange={(e) => updateProfileField("has_medical_condition", e.target.checked)}
              />
              Tengo una patología o tomo medicación que afecta a mi alimentación
            </label>
          </fieldset>

          {profileError && <p className="text-sm text-red-600 dark:text-red-400 sm:col-span-2">{profileError}</p>}
          {profileSaved && (
            <p className="text-sm text-[var(--color-primary)] sm:col-span-2">Perfil guardado.</p>
          )}

          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={profileSaving}
              className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
            >
              {profileSaving ? "Guardando…" : "Guardar perfil"}
            </button>
          </div>
        </form>
      </section>

      <RestrictionsPanel />

      <section id="medida" className="scroll-mt-20">
        <h2 className="mb-4 text-xl font-semibold">Nueva medida corporal</h2>
        <form onSubmit={onSaveMeasurement} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Fecha
            <input
              type="date"
              required
              className={inputClass}
              value={measuredOn}
              onChange={(e) => setMeasuredOn(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Peso (kg)
            <input
              type="number"
              step="0.1"
              className={inputClass}
              value={weightKg}
              onChange={(e) => setWeightKg(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            % grasa corporal (opcional)
            <input
              type="number"
              step="0.1"
              className={inputClass}
              value={bodyFatPct}
              onChange={(e) => setBodyFatPct(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={measurementSaving}
            className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {measurementSaving ? "Guardando…" : "Guardar medida"}
          </button>
        </form>
        {measurementError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{measurementError}</p>}

        <div className="mt-6">
          <h3 className="mb-3 text-lg font-bold tracking-tight">Tendencia de peso</h3>
          <WeightTrend points={weightSeries} />
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold">Cálculos</h2>
        <MedicalDisclaimer />
        <button
          type="button"
          onClick={onCalculate}
          disabled={calcLoading}
          className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
        >
          {calcLoading ? "Calculando…" : "Calcular BMR / TDEE / objetivos"}
        </button>

        {calcError && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{calcError}</p>}

        {bmr && (
          <div className="mt-4 flex gap-6 text-sm">
            <div>
              <p className="text-neutral-500">BMR</p>
              <p className="text-lg font-semibold">{bmr.bmr} kcal</p>
            </div>
            <div>
              <p className="text-neutral-500">TDEE</p>
              <p className="text-lg font-semibold">{bmr.tdee} kcal</p>
            </div>
            <div>
              <p className="text-neutral-500">Fórmula</p>
              <p className="text-lg font-semibold">{bmr.formula_used}</p>
            </div>
          </div>
        )}

        {targets && (
          <div className="mt-6">
            <p className="text-sm text-neutral-500">
              Objetivo calórico: <span className="font-semibold text-current">{targets.kcal} kcal/día</span>{" "}
              · Agua: {targets.water_ml} ml
            </p>
            <p className="mt-1 text-xs text-neutral-400">
              {targets.source === "adaptive_tdee"
                ? "Calculado con tu TDEE adaptativo (tendencia real de peso e ingesta de las últimas 2 semanas)."
                : "Calculado con la fórmula de Mifflin-St Jeor. Pasará a tu TDEE adaptativo en cuanto tengas ≥10 días de registro en las últimas 2 semanas."}
            </p>
            {targets.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-amber-600">
                {targets.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            <div className="mt-3 max-w-sm">
              <BarChart data={macroData} unit=" g" />
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
