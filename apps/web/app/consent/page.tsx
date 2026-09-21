"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";

/** Consentimiento explícito del tratamiento de datos de salud (RGPD art. 9.2.a, R4).
 * Se bloquea el uso de la app hasta aceptarlo (`ConsentGate`). */
export default function ConsentPage() {
  const router = useRouter();
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAccept(e: React.FormEvent) {
    e.preventDefault();
    if (!accepted) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/consents", {
        method: "POST",
        body: JSON.stringify({ kind: "health_data", version: "v1" }),
      });
      router.push("/profile");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-5 px-4 py-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Tus datos de salud</h1>
      <p className="text-sm">
        MyFood guarda información sobre tu salud: tu peso, medidas corporales, sexo, edad, altura,
        lo que comes y bebes, tus suplementos y tus planes de dieta. La ley (RGPD, art. 9) la
        considera una categoría especial y solo puede tratarse con tu consentimiento explícito.
      </p>

      <section className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4 text-sm">
        <h2 className="font-semibold">Qué haremos con ellos</h2>
        <ul className="list-disc pl-5">
          <li>Calcular tus objetivos (metabolismo, calorías, macronutrientes, agua) y tu progreso.</li>
          <li>Generar y ajustar planes de dieta, listas de la compra y recordatorios.</li>
          <li>
            <strong>Nada sale de este servidor</strong> salvo lo que tú activas aparte (iafood: se
            envían a Claude solo objetivos y restricciones anonimizados, nunca tu nombre ni tu
            email; requiere un segundo consentimiento distinto).
          </li>
        </ul>
        <h2 className="mt-2 font-semibold">Cómo los protegemos</h2>
        <ul className="list-disc pl-5">
          <li>Perfil y medidas cifrados en la base de datos, y aislados por usuario.</li>
          <li>Se alojan en un servidor propio, sin terceros ni publicidad.</li>
        </ul>
        <h2 className="mt-2 font-semibold">Tus derechos</h2>
        <p>
          Puedes verlos, <strong>exportarlos</strong>, <strong>revocar</strong> este consentimiento
          y <strong>borrar tu cuenta</strong> con todos tus datos, cuando quieras, desde{" "}
          <Link href="/privacy" className="underline">
            Privacidad
          </Link>
          . Revocarlo impide guardar nuevos datos de salud.
        </p>
      </section>

      <form onSubmit={onAccept} className="flex flex-col gap-3">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
            className="mt-0.5"
          />
          Consiento el tratamiento de mis datos de salud para los fines descritos.
        </label>
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={!accepted || busy}
            className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {busy ? "Guardando…" : "Aceptar y continuar"}
          </button>
          <Link href="/privacy" className="text-sm text-neutral-500 underline">
            No acepto: ver privacidad / borrar mi cuenta
          </Link>
        </div>
      </form>
    </main>
  );
}
