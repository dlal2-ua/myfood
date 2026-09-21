"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { ConsentStatus } from "@/lib/types";

const LABELS: Record<string, { title: string; detail: string }> = {
  health_data: {
    title: "Tratamiento de mis datos de salud",
    detail: "Peso, medidas, perfil, registro de comidas y planes. Necesario para usar la app.",
  },
  ai_processing: {
    title: "Envío anonimizado a Claude (iafood)",
    detail:
      "Objetivos y restricciones sin nombre ni email, para generar planes, Smart Log y el chat. Opcional.",
  },
};

/** Ver, conceder y revocar los consentimientos (RGPD art. 7.3: revocar es tan fácil
 * como conceder). */
export function ConsentsPanel() {
  const [items, setItems] = useState<ConsentStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyKind, setBusyKind] = useState<string | null>(null);

  async function load() {
    try {
      setItems(await apiFetch<ConsentStatus[]>("/api/consents"));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function toggle(item: ConsentStatus) {
    setBusyKind(item.kind);
    setError(null);
    try {
      if (item.granted) {
        await apiFetch(`/api/consents/${item.kind}`, { method: "DELETE" });
      } else {
        await apiFetch("/api/consents", {
          method: "POST",
          body: JSON.stringify({ kind: item.kind, version: "v1" }),
        });
      }
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyKind(null);
    }
  }

  if (items.length === 0 && !error) return null;

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Consentimientos</h2>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <ul className="flex flex-col gap-2">
        {items.map((item) => {
          const label = LABELS[item.kind] ?? { title: item.kind, detail: "" };
          return (
            <li
              key={item.kind}
              className="flex items-start justify-between gap-3 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-3 text-sm"
            >
              <div>
                <p className="font-medium">
                  {label.title}{" "}
                  <span className="text-xs font-normal text-neutral-500">
                    {item.required ? "(obligatorio)" : "(opcional)"}
                  </span>
                </p>
                <p className="text-neutral-500">{label.detail}</p>
                <p className="mt-1 text-xs text-neutral-500">
                  {item.granted
                    ? `Concedido el ${new Date(item.granted_at ?? "").toLocaleDateString("es-ES")}`
                    : item.revoked_at
                      ? `Revocado el ${new Date(item.revoked_at).toLocaleDateString("es-ES")}`
                      : "No concedido"}
                </p>
              </div>
              <button
                type="button"
                disabled={busyKind === item.kind}
                onClick={() => void toggle(item)}
                className="shrink-0 rounded-full border border-[var(--color-border-strong)] font-medium px-3 py-1.5 disabled:opacity-60"
              >
                {item.granted ? "Revocar" : "Conceder"}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
