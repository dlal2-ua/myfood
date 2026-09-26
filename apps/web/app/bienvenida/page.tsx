"use client";

import { ArrowRight, Camera, Check, MessageSquareText, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { localDateIso } from "@/lib/dates";
import type { Profile, TargetsResponse } from "@/lib/types";

/** Puesta a punto en tres pasos, para quien acaba de entrar.
 *
 * Existe porque cinco de los ocho primeros usuarios se registraron y no apuntaron ni una
 * comida: lo primero que veían era un marcador a cero y un enlace a un formulario largo. Aquí
 * se pregunta solo lo que hace falta para calcular unas calorías objetivo, en tres pantallas
 * cortas, y se puede saltar entero — apuntar comida nunca ha necesitado perfil y sigue sin
 * necesitarlo.
 */

const GOALS = [
  { value: "lose", label: "Perder peso", hint: "Un déficit suave y sostenible." },
  { value: "maintain", label: "Mantener", hint: "Comer para quedarte como estás." },
  { value: "gain", label: "Ganar peso", hint: "Un superávit para coger masa." },
] as const;

const ACTIVITY = [
  { value: "sedentary", label: "Poco", hint: "Trabajo sentado, poco ejercicio" },
  { value: "light", label: "Algo", hint: "1-3 días de ejercicio por semana" },
  { value: "moderate", label: "Bastante", hint: "3-5 días por semana" },
  { value: "active", label: "Mucho", hint: "6-7 días por semana" },
  { value: "very_active", label: "Muchísimo", hint: "Trabajo físico o dos sesiones al día" },
] as const;

const card =
  "rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)]";
const input =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";
const primary =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-[var(--color-primary)] px-5 font-semibold text-[var(--color-on-primary)] hover:bg-[var(--color-primary-hover)] disabled:opacity-60";

/** Una opción entre varias: toda la fila es pulsable, no solo un radio diminuto. */
function Choice({
  label,
  hint,
  selected,
  onSelect,
}: {
  label: string;
  hint: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex min-h-14 w-full items-center gap-3 rounded-[var(--radius-control)] border px-4 py-3 text-left transition-colors ${
        selected
          ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)]"
          : "border-[var(--color-border-strong)] hover:bg-[var(--color-surface-2)]"
      }`}
    >
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{label}</span>
        <span className="block text-xs text-[var(--color-muted)]">{hint}</span>
      </span>
      {selected && <Check size={18} aria-hidden="true" className="text-[var(--color-primary)]" />}
    </button>
  );
}

/** Saltárselo tiene que ser fácil: apuntar comida nunca ha necesitado perfil. */
function SaltarAlDiario() {
  return (
    <p className="text-center text-sm">
      <Link href="/log#registrar" className="text-[var(--color-muted)] underline">
        Prefiero empezar a apuntar y rellenar esto luego
      </Link>
    </p>
  );
}

export default function BienvenidaPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [goal, setGoal] = useState<Profile["goal"] | null>(null);
  const [sex, setSex] = useState<"male" | "female" | null>(null);
  const [birthDate, setBirthDate] = useState("");
  const [heightCm, setHeightCm] = useState("");
  const [weightKg, setWeightKg] = useState("");
  const [activity, setActivity] = useState<Profile["activity_level"]>("light");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targets, setTargets] = useState<TargetsResponse | null>(null);

  const datosCompletos = Boolean(sex && birthDate && Number(heightCm) > 0 && Number(weightKg) > 0);

  async function guardar() {
    setSaving(true);
    setError(null);
    try {
      await apiFetch("/api/profile", {
        method: "PUT",
        body: JSON.stringify({
          goal,
          sex,
          birth_date: birthDate,
          height_cm: Number(heightCm),
          activity_level: activity,
        }),
      });
      await apiFetch("/api/measurements", {
        method: "POST",
        body: JSON.stringify({ measured_on: localDateIso(), weight_kg: Number(weightKg) }),
      });
      // Los objetivos se piden aquí para poder enseñarlos: son la recompensa de haber
      // rellenado esto, y sin ellos el asistente es un formulario más.
      setTargets(await apiFetch<TargetsResponse>("/api/calc/targets"));
      setStep(3);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-lg flex-col gap-5">
      <div>
        <p className="text-sm font-semibold text-[var(--color-primary)]">Paso {step} de 3</p>
        <div className="mt-2 flex gap-1.5" aria-hidden="true">
          {[1, 2, 3].map((n) => (
            <span
              key={n}
              className={`h-1.5 flex-1 rounded-full ${
                n <= step ? "bg-[var(--color-primary)]" : "bg-[var(--color-border)]"
              }`}
            />
          ))}
        </div>
      </div>

      {step === 1 && (
        <>
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">¿Qué quieres conseguir?</h1>
            <p className="mt-1 text-sm text-[var(--color-muted)]">
              Con esto y cuatro datos más calculo cuántas calorías te tocan al día. Puedes
              cambiarlo cuando quieras.
            </p>
          </div>
          <div className="flex flex-col gap-2">
            {GOALS.map((g) => (
              <Choice
                key={g.value}
                label={g.label}
                hint={g.hint}
                selected={goal === g.value}
                onSelect={() => setGoal(g.value)}
              />
            ))}
          </div>
          <button type="button" disabled={!goal} onClick={() => setStep(2)} className={primary}>
            Seguir <ArrowRight size={18} aria-hidden="true" />
          </button>
          <SaltarAlDiario />
        </>
      )}

      {step === 2 && (
        <>
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">Cuéntame lo básico</h1>
            <p className="mt-1 text-sm text-[var(--color-muted)]">
              Hacen falta para la fórmula del gasto energético. No salen de tu servidor.
            </p>
          </div>
          <div className={`${card} flex flex-col gap-4 p-4`}>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-semibold">Sexo</legend>
              <div className="flex gap-2">
                {(["female", "male"] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setSex(value)}
                    aria-pressed={sex === value}
                    className={`min-h-11 flex-1 rounded-[var(--radius-control)] border font-semibold ${
                      sex === value
                        ? "border-[var(--color-primary)] bg-[var(--color-primary-soft)]"
                        : "border-[var(--color-border-strong)]"
                    }`}
                  >
                    {value === "female" ? "Mujer" : "Hombre"}
                  </button>
                ))}
              </div>
              <p className="text-xs text-[var(--color-muted)]">
                Las fórmulas de metabolismo basal lo usan; no hay más opciones porque las
                fórmulas no las tienen.
              </p>
            </fieldset>

            <label className="flex flex-col gap-1.5 text-sm font-semibold">
              Fecha de nacimiento
              <input
                type="date"
                className={input}
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1.5 text-sm font-semibold">
                Altura (cm)
                <input
                  type="number"
                  inputMode="decimal"
                  min={80}
                  max={272}
                  className={input}
                  value={heightCm}
                  onChange={(e) => setHeightCm(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1.5 text-sm font-semibold">
                Peso (kg)
                <input
                  type="number"
                  inputMode="decimal"
                  min={20}
                  max={500}
                  step="0.1"
                  className={input}
                  value={weightKg}
                  onChange={(e) => setWeightKg(e.target.value)}
                />
              </label>
            </div>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-semibold">¿Cuánto te mueves?</legend>
              {ACTIVITY.map((a) => (
                <Choice
                  key={a.value}
                  label={a.label}
                  hint={a.hint}
                  selected={activity === a.value}
                  onSelect={() => setActivity(a.value)}
                />
              ))}
            </fieldset>
          </div>
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="min-h-11 rounded-full border border-[var(--color-border-strong)] px-4 font-medium"
            >
              Atrás
            </button>
            <button
              type="button"
              disabled={!datosCompletos || saving}
              onClick={() => void guardar()}
              className={`${primary} flex-1`}
            >
              {saving ? "Calculando…" : "Calcular mis calorías"}
            </button>
          </div>
          <SaltarAlDiario />
        </>
      )}

      {step === 3 && (
        <>
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">Listo</h1>
            <p className="mt-1 text-sm text-[var(--color-muted)]">
              Esto es lo que te toca al día. Se ajusta solo según lo que vayas registrando.
            </p>
          </div>
          {targets && (
            <div className={`${card} p-5 text-center`}>
              <p className="text-5xl font-extrabold tracking-tight">
                {Math.round(targets.kcal)}
                <span className="ml-1 text-xl font-bold text-[var(--color-muted)]">kcal</span>
              </p>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-sm">
                {(
                  [
                    ["Proteína", targets.protein_g, "var(--color-protein)"],
                    ["Carbos", targets.carbs_g, "var(--color-carbs)"],
                    ["Grasa", targets.fat_g, "var(--color-fat)"],
                  ] as const
                ).map(([label, value, color]) => (
                  <div key={label}>
                    <dt className="text-xs text-[var(--color-muted)]">{label}</dt>
                    <dd className="font-bold" style={{ color }}>
                      {Math.round(value)} g
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          <p className="text-sm font-semibold">Ahora apunta lo primero que comas:</p>
          <div className="grid grid-cols-3 gap-2">
            {[
              { href: "/log#foto", icon: Camera, label: "Una foto" },
              { href: "/log#natural", icon: MessageSquareText, label: "Escribirlo" },
              { href: "/foods", icon: Search, label: "Buscarlo" },
            ].map(({ href, icon: Icon, label }) => (
              <Link
                key={href}
                href={href}
                className={`${card} flex min-h-24 flex-col items-center justify-center gap-2 p-3 text-center text-sm font-semibold hover:bg-[var(--color-surface-2)]`}
              >
                <Icon size={22} aria-hidden="true" className="text-[var(--color-primary)]" />
                {label}
              </Link>
            ))}
          </div>
          <button
            type="button"
            onClick={() => router.push("/")}
            className="min-h-11 rounded-full border border-[var(--color-border-strong)] font-medium"
          >
            Ir a mi día
          </button>
        </>
      )}
    </main>
  );
}
