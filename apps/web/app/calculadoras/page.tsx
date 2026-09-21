"use client";

import { useState } from "react";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { apiFetch, errorMessage } from "@/lib/api";
import type { BmrFormula, BmrResponse, BodyFatMethod, BodyFatResult } from "@/lib/types";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

const BMR_FORMULAS: { value: BmrFormula; label: string; needsBodyFat: boolean }[] = [
  { value: "mifflin", label: "Mifflin-St Jeor (recomendada)", needsBodyFat: false },
  { value: "harris", label: "Harris-Benedict revisada", needsBodyFat: false },
  { value: "katch", label: "Katch-McArdle (usa tu % de grasa)", needsBodyFat: true },
  { value: "cunningham", label: "Cunningham (usa tu % de grasa)", needsBodyFat: true },
];

const METHODS: { value: BodyFatMethod; label: string; help: string }[] = [
  { value: "navy", label: "US Navy (cinta métrica)", help: "Cuello, cintura y, en mujeres, cadera." },
  { value: "jackson3", label: "Jackson-Pollock, 3 pliegues", help: "Pliegues con lipocalibre." },
  { value: "jackson7", label: "Jackson-Pollock, 7 pliegues", help: "Pliegues con lipocalibre." },
  { value: "durnin", label: "Durnin-Womersley, 4 pliegues", help: "Válida desde los 17 años." },
  { value: "deurenberg", label: "Deurenberg (solo IMC y edad)", help: "La menos precisa." },
];

const SITE_LABELS: Record<string, string> = {
  chest: "Pecho",
  abdomen: "Abdomen",
  thigh: "Muslo",
  triceps: "Tríceps",
  suprailiac: "Suprailíaco",
  subscapular: "Subescapular",
  midaxillary: "Axilar medio",
  biceps: "Bíceps",
};

function sitesFor(method: BodyFatMethod, sex: string): string[] {
  if (method === "jackson3")
    return sex === "female" ? ["triceps", "suprailiac", "thigh"] : ["chest", "abdomen", "thigh"];
  if (method === "jackson7")
    return ["chest", "midaxillary", "triceps", "subscapular", "abdomen", "suprailiac", "thigh"];
  if (method === "durnin") return ["biceps", "triceps", "subscapular", "suprailiac"];
  return [];
}

const WARNINGS: Record<string, string> = {
  BODY_FAT_OUT_OF_RANGE:
    "El resultado queda fuera de un rango razonable (3–60 %): revisa las medidas, este método no es fiable con ellas.",
  MISSING_WEIGHT_FOR_LEAN_MASS: "Sin tu peso no se puede calcular la masa magra ni el FFMI.",
  BMI_BASED_ESTIMATE:
    "Este método solo estima a partir del IMC: infravalora la grasa en personas musculadas y la sobrevalora en mayores.",
  DURNIN_NOT_VALIDATED_UNDER_17: "Durnin-Womersley no está validada por debajo de los 17 años.",
  WAIST_TO_HEIGHT_RISK:
    "Tu cintura supera la mitad de tu altura (0,5). Es un indicador de riesgo cardiometabólico: coméntalo con tu profesional sanitario.",
};

function BmrCalculator() {
  const [formula, setFormula] = useState<BmrFormula>("mifflin");
  const [result, setResult] = useState<BmrResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onCalculate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(
        await apiFetch<BmrResponse>("/api/calc/bmr", {
          method: "POST",
          body: JSON.stringify({ formula }),
        }),
      );
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
      <h2 className="text-lg font-semibold">Metabolismo basal y gasto diario</h2>
      <p className="text-sm text-neutral-500">
        Usa tu perfil (sexo, edad, altura, actividad) y tu última pesada.
      </p>
      <form onSubmit={onCalculate} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Fórmula
          <select
            className={inputClass}
            value={formula}
            onChange={(e) => setFormula(e.target.value as BmrFormula)}
          >
            {BMR_FORMULAS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
        >
          Calcular
        </button>
      </form>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {result && (
        <dl className="grid grid-cols-2 gap-3 text-sm" aria-live="polite">
          <div className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
            <dt className="text-xs text-neutral-500">Metabolismo basal (TMB)</dt>
            <dd className="text-xl font-semibold">{result.bmr} kcal</dd>
          </div>
          <div className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
            <dt className="text-xs text-neutral-500">Gasto diario (TDEE)</dt>
            <dd className="text-xl font-semibold">{result.tdee} kcal</dd>
          </div>
        </dl>
      )}
    </section>
  );
}

function BodyFatCalculator() {
  const [method, setMethod] = useState<BodyFatMethod>("navy");
  const [sex, setSex] = useState("male");
  const [age, setAge] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<BodyFatResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const sites = sitesFor(method, sex);
  const set = (key: string, value: string) => setValues((prev) => ({ ...prev, [key]: value }));

  async function onCalculate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { method, sex };
    const numeric = (key: string) => (values[key] ? Number(values[key]) : undefined);
    if (age) body.age_years = Number(age);
    for (const key of ["height_cm", "weight_kg", "neck_cm", "waist_cm", "hip_cm"]) {
      if (values[key]) body[key] = numeric(key);
    }
    for (const site of sites) body[`${site}_mm`] = numeric(site);
    try {
      setResult(
        await apiFetch<BodyFatResult>("/api/calc/body-fat", {
          method: "POST",
          body: JSON.stringify(body),
        }),
      );
    } catch (err) {
      setResult(null);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const number = (key: string, label: string, required = false, step = "0.1") => (
    <label key={key} className="flex flex-col gap-1 text-sm">
      {label}
      <input
        type="number"
        min={0}
        step={step}
        required={required}
        className={inputClass}
        value={values[key] ?? ""}
        onChange={(e) => set(key, e.target.value)}
      />
    </label>
  );

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
      <h2 className="text-lg font-semibold">Grasa corporal, masa magra y FFMI</h2>
      <form onSubmit={onCalculate} className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Método
            <select
              className={inputClass}
              value={method}
              onChange={(e) => setMethod(e.target.value as BodyFatMethod)}
            >
              {METHODS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Sexo
            <select className={inputClass} value={sex} onChange={(e) => setSex(e.target.value)}>
              <option value="male">Hombre</option>
              <option value="female">Mujer</option>
            </select>
          </label>
        </div>
        <p className="text-xs text-neutral-500">{METHODS.find((m) => m.value === method)?.help}</p>
        <div className="flex flex-wrap gap-3">
          {number("height_cm", "Altura (cm)", true)}
          {number("weight_kg", "Peso (kg)", method === "deurenberg")}
          {method !== "navy" && (
            <label className="flex flex-col gap-1 text-sm">
              Edad (años)
              <input
                type="number"
                min={10}
                max={110}
                required
                className={inputClass}
                value={age}
                onChange={(e) => setAge(e.target.value)}
              />
            </label>
          )}
          {method === "navy" && (
            <>
              {number("neck_cm", "Cuello (cm)", true)}
              {number("waist_cm", "Cintura (cm)", true)}
              {sex === "female" && number("hip_cm", "Cadera (cm)", true)}
            </>
          )}
          {sites.map((site) => number(site, `${SITE_LABELS[site]} (mm)`, true))}
          {method !== "navy" && number("waist_cm", "Cintura (cm, opcional)")}
        </div>
        <button
          type="submit"
          disabled={busy}
          className="w-fit rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
        >
          Calcular
        </button>
      </form>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {result && (
        <div aria-live="polite" className="flex flex-col gap-3">
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {[
              ["Grasa corporal", `${result.body_fat_pct} %`],
              ["Masa magra", result.lean_mass_kg != null ? `${result.lean_mass_kg} kg` : "—"],
              ["FFMI", result.ffmi != null ? String(result.ffmi) : "—"],
              ["IMC", result.bmi != null ? String(result.bmi) : "—"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3">
                <dt className="text-xs text-neutral-500">{label}</dt>
                <dd className="text-xl font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
          {result.whtr != null && (
            <p className="text-sm">
              Cintura/altura: <strong>{result.whtr}</strong>
            </p>
          )}
          {result.bmi != null && (
            <p className="text-xs text-neutral-500">
              El IMC no distingue entre grasa y músculo: una persona con mucha masa muscular puede
              tener un IMC alto sin exceso de grasa.
            </p>
          )}
          {result.warnings.map((w) => (
            <p key={w} className="text-xs text-amber-800 dark:text-amber-300">
              {WARNINGS[w] ?? w}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

export default function CalculatorsPage() {
  return (
    <main className="flex max-w-2xl flex-col gap-6">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Calculadoras</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Todos los cálculos se hacen en el servidor con fórmulas publicadas; nada de esto pasa por la
          IA.
        </p>
      </div>
      <MedicalDisclaimer />
      <BmrCalculator />
      <BodyFatCalculator />
    </main>
  );
}
