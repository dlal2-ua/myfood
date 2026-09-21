"use client";

import { localDateIso } from "@/lib/dates";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import {
  HealthConnect,
  isNativeApp,
  type HealthConnectAvailability,
  type HealthConnectRecent,
} from "@/lib/healthConnect";
import type { LogDay, WaterDay } from "@/lib/types";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

function todayIso(): string {
  return localDateIso();
}

function startOfTodayIso(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

export default function WearablesPage() {
  const [native, setNative] = useState(false);
  const [availability, setAvailability] = useState<HealthConnectAvailability | null>(null);
  // Health Connect concede lectura y escritura por separado (el usuario
  // puede aceptar una y rechazar la otra en el mismo diálogo) — de ahí dos
  // banderas en vez de un único "granted" que ocultaría esa diferencia.
  const [canRead, setCanRead] = useState(false);
  const [canWrite, setCanWrite] = useState(false);
  const [recent, setRecent] = useState<HealthConnectRecent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const isNative = isNativeApp();
    setNative(isNative);
    if (!isNative) return;
    HealthConnect.checkAvailability()
      .then(setAvailability)
      .catch((err) => setError(errorMessage(err)));
    HealthConnect.checkHealthPermissions()
      .then((r) => {
        setCanRead(r.canRead);
        setCanWrite(r.canWrite);
      })
      .catch(() => {});
  }, []);

  async function onRequestPermissions() {
    setBusy(true);
    setError(null);
    try {
      const result = await HealthConnect.requestHealthPermissions();
      setCanRead(result.canRead);
      setCanWrite(result.canWrite);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onImport() {
    setBusy(true);
    setError(null);
    try {
      setRecent(await HealthConnect.readRecent({ days: 14 }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onLogWeight(time: string, kg: number) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await apiFetch("/api/measurements", {
        method: "POST",
        body: JSON.stringify({
          measured_on: time.slice(0, 10),
          weight_kg: Math.round(kg * 10) / 10,
          source: "health_connect",
        }),
      });
      setMessage("Peso registrado en MyFood.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onLogBodyFat(time: string, percentage: number) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await apiFetch("/api/measurements", {
        method: "POST",
        body: JSON.stringify({
          measured_on: time.slice(0, 10),
          body_fat_pct: Math.round(percentage * 10) / 10,
          source: "health_connect",
        }),
      });
      setMessage("Grasa corporal registrada en MyFood.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onExportToday() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const startTime = startOfTodayIso();
      const endTime = new Date().toISOString();

      const water = await apiFetch<WaterDay>(`/api/water/log?date=${todayIso()}`);
      if (water.total_ml > 0) {
        await HealthConnect.writeHydration({ ml: water.total_ml, startTime, endTime });
      }

      const day = await apiFetch<LogDay>(`/api/log?date=${todayIso()}`);
      if (day.totals.kcal > 0) {
        await HealthConnect.writeNutrition({
          kcal: day.totals.kcal,
          proteinG: day.totals.protein_g,
          fatG: day.totals.fat_g,
          carbsG: day.totals.carbs_g,
          startTime,
          endTime,
        });
      }
      setMessage("Registros de hoy exportados a Health Connect.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!native) {
    return (
      <main className="flex flex-col gap-4">
        <h1 className="text-3xl font-extrabold tracking-tight">Wearables</h1>
        <p className="text-sm text-neutral-500">
          Esta sección solo está disponible en la app Android de MyFood — necesita Health
          Connect, una API nativa sin equivalente en el navegador.
        </p>
      </main>
    );
  }

  return (
    <main className="flex flex-col gap-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Wearables (Health Connect)</h1>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {message && <p className="text-sm text-neutral-600 dark:text-neutral-400">{message}</p>}

      <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
        <h2 className="mb-3 text-lg font-semibold">Estado</h2>
        {availability && !availability.available && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Health Connect no está disponible en este dispositivo
            {availability.status === "update_required" && " (necesita actualizarse)"}.
          </p>
        )}
        {availability?.available && (
          <div className="flex items-center gap-3">
            <p className="text-sm">
              Lectura: <span className="font-medium">{canRead ? "concedida" : "pendiente"}</span>
              {" · "}
              Escritura: <span className="font-medium">{canWrite ? "concedida" : "pendiente"}</span>
            </p>
            {!(canRead && canWrite) && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void onRequestPermissions()}
                className={`${inputClass} bg-[var(--color-primary)] text-[var(--color-on-primary)] disabled:opacity-60`}
              >
                Conceder permisos
              </button>
            )}
          </div>
        )}
      </section>

      {canRead && (
        <>
          <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
            <h2 className="mb-3 text-lg font-semibold">Importar desde Health Connect</h2>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onImport()}
              className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
            >
              Importar últimos 14 días
            </button>

            {recent && (
              <div className="mt-4 flex flex-col gap-4">
                <div className="flex gap-6 text-sm">
                  <div>
                    <p className="text-neutral-500">Pasos (14 días)</p>
                    <p className="font-semibold">{recent.stepsTotal}</p>
                  </div>
                  <div>
                    <p className="text-neutral-500">Kcal activas (14 días)</p>
                    <p className="font-semibold">{Math.round(recent.activeKcalTotal)}</p>
                  </div>
                </div>

                {recent.weights.length > 0 && (
                  <div>
                    <p className="mb-2 text-sm font-medium">Peso</p>
                    <ul className="flex flex-col gap-1">
                      {recent.weights.map((w, i) => (
                        <li key={i} className="flex items-center gap-3 text-sm">
                          <span>
                            {new Date(w.time).toLocaleString()} — {w.kg.toFixed(1)} kg
                          </span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void onLogWeight(w.time, w.kg)}
                            className="text-[var(--color-primary)] underline disabled:opacity-60"
                          >
                            Registrar en MyFood
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {recent.bodyFat.length > 0 && (
                  <div>
                    <p className="mb-2 text-sm font-medium">Grasa corporal</p>
                    <ul className="flex flex-col gap-1">
                      {recent.bodyFat.map((b, i) => (
                        <li key={i} className="flex items-center gap-3 text-sm">
                          <span>
                            {new Date(b.time).toLocaleString()} — {b.percentage.toFixed(1)}%
                          </span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void onLogBodyFat(b.time, b.percentage)}
                            className="text-[var(--color-primary)] underline disabled:opacity-60"
                          >
                            Registrar en MyFood
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        </>
      )}

      {canWrite && (
        <section className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-4">
          <h2 className="mb-3 text-lg font-semibold">Exportar a Health Connect</h2>
          <p className="mb-3 text-sm text-neutral-500">
            Envía el agua y la comida ya registradas hoy en MyFood a Health Connect, para
            que otras apps conectadas (p. ej. Samsung Health) también las vean.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void onExportToday()}
            className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            Exportar hoy
          </button>
        </section>
      )}
    </main>
  );
}
