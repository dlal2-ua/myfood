"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, errorMessage } from "@/lib/api";
import { ConsentsPanel } from "@/components/ConsentsPanel";
import type { PrivacySummary } from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

export default function PrivacyPage() {
  const router = useRouter();
  const [summary, setSummary] = useState<PrivacySummary | null>(null);
  const [authenticated, setAuthenticated] = useState(false);

  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PrivacySummary>("/api/privacy/summary")
      .then((data) => {
        setSummary(data);
        setAuthenticated(true);
      })
      .catch(() => {
        // Sin sesión iniciada: la página se queda solo con el texto legal.
        setAuthenticated(false);
      });
  }, []);

  async function onDeleteAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!password || !confirmed) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await apiFetch("/api/privacy/delete-account", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      router.push("/login");
      router.refresh();
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleting(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-8">
      <h1 className="text-xl font-semibold">Privacidad de datos de salud</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        MyFood es una aplicación autoalojada de uso personal/familiar. Cuando accede a
        Health Connect, lo hace solo para:
      </p>
      <ul className="list-disc pl-5 text-sm text-neutral-600 dark:text-neutral-400">
        <li>Leer peso, grasa corporal, pasos y calorías activas que tú decides importar.</li>
        <li>
          Escribir en Health Connect el agua y la comida que ya has registrado tú mismo en
          MyFood, para que otras apps conectadas (p. ej. Samsung Health) también lo vean.
        </li>
      </ul>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Ningún dato de salud sale del servidor donde tú mismo alojas MyFood ni se comparte
        con terceros. Puedes revocar el acceso en cualquier momento desde los ajustes de
        Health Connect de tu dispositivo.
      </p>

      {authenticated && summary && (
        <>
          <hr className="my-4 border-neutral-200 dark:border-neutral-800" />

          <section className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold">Tus datos</h2>
            <p className="text-sm text-neutral-500">
              Cuenta creada el {new Date(summary.account_created_at).toLocaleDateString("es-ES")}.
            </p>
            <ul className="list-disc pl-5 text-sm text-neutral-600 dark:text-neutral-400">
              <li>{summary.measurements_count} medidas corporales registradas</li>
              <li>{summary.food_log_entries} entradas en el registro de comidas</li>
              <li>{summary.water_log_entries} registros de agua</li>
              <li>{summary.supplements_count} suplementos</li>
              <li>{summary.diet_plans_count} planes de dieta</li>
              <li>{summary.recipes_count} recetas</li>
            </ul>
            <a
              href="/api/privacy/export"
              className="mt-2 inline-block w-fit rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm text-white"
            >
              Descargar todos mis datos (JSON)
            </a>
          </section>

          <ConsentsPanel />

          <section className="mt-6 flex flex-col gap-3 rounded-lg border border-red-300 p-4 dark:border-red-900">
            <h2 className="text-lg font-semibold text-red-700 dark:text-red-400">
              Eliminar mi cuenta y todos mis datos
            </h2>
            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              Borra tu perfil, medidas, registro, planes, recetas, despensa, lista de la compra
              y suplementos. Es inmediato e irreversible.
            </p>
            <form onSubmit={onDeleteAccount} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-sm">
                Confirma tu contraseña
                <input
                  type="password"
                  className={inputClass}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                Entiendo que esto elimina mi cuenta y todos mis datos de forma permanente.
              </label>
              <button
                type="submit"
                disabled={deleting || !password || !confirmed}
                className="w-fit rounded-lg bg-red-600 px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {deleting ? "Eliminando…" : "Eliminar mi cuenta"}
              </button>
              {deleteError && <p className="text-sm text-red-600">{deleteError}</p>}
            </form>
          </section>
        </>
      )}
    </main>
  );
}
