"use client";

import { useCallback, useEffect, useState } from "react";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import type { Fasting, FastingStats } from "@/lib/types";

const PRESETS = [
  { hours: 12, label: "12:12" },
  { hours: 14, label: "14:10" },
  { hours: 16, label: "16:8" },
  { hours: 18, label: "18:6" },
  { hours: 20, label: "20:4" },
];

function formatDuration(hours: number): string {
  const total = Math.max(0, Math.round(hours * 60));
  return `${Math.floor(total / 60)} h ${String(total % 60).padStart(2, "0")} min`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Ring({ fraction, children }: { fraction: number; children: React.ReactNode }) {
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const shown = Math.min(1, Math.max(0, fraction));
  return (
    <div className="relative mx-auto h-44 w-44">
      <svg viewBox="0 0 176 176" className="h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="88" cy="88" r={radius} fill="none" stroke="currentColor" opacity={0.12} strokeWidth="10" />
        <circle
          cx="88"
          cy="88"
          r={radius}
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - shown)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        {children}
      </div>
    </div>
  );
}

export default function FastingPage() {
  const [current, setCurrent] = useState<Fasting | null>(null);
  const [history, setHistory] = useState<Fasting[]>([]);
  const [stats, setStats] = useState<FastingStats | null>(null);
  const [target, setTarget] = useState(16);
  const [custom, setCustom] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [cur, hist, st] = await Promise.all([
        apiFetch<Fasting | null>("/api/fasting/current"),
        apiFetch<Fasting[]>("/api/fasting/history?limit=14"),
        apiFetch<FastingStats>("/api/fasting/stats?days=30"),
      ]);
      setCurrent(cur);
      setHistory(hist);
      setStats(st);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/fasting/start", {
        method: "POST",
        body: JSON.stringify({ target_hours: target }),
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function end() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/fasting/${current.id}/end`, { method: "POST", body: JSON.stringify({}) });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("¿Eliminar este ayuno del historial?")) return;
    try {
      await apiFetch(`/api/fasting/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  // El temporizador se calcula en el cliente a partir de `started_at` para que avance entre
  // recargas sin pedir nada al servidor cada segundo.
  const elapsedHours = current
    ? Math.max(0, (now - new Date(current.started_at).getTime()) / 3_600_000)
    : 0;
  const remaining = current ? Math.max(0, current.target_hours - elapsedHours) : 0;
  const reached = current ? elapsedHours >= current.target_hours : false;

  if (loading) return <p className="text-sm text-neutral-500">Cargando…</p>;

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Ayuno</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Temporizador de ayuno intermitente. Romper un ayuno antes de tiempo no es un fallo: solo
          queda registrado.
        </p>
      </div>
      <MedicalDisclaimer>
        El ayuno intermitente no es adecuado para todo el mundo (embarazo, lactancia, menores,
        diabetes o medicación, historial de trastornos de la conducta alimentaria). Consúltalo con
        un profesional sanitario antes de empezar y detén el ayuno si te encuentras mal.
      </MedicalDisclaimer>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {current ? (
        <section className="flex flex-col items-center gap-4 rounded-lg border border-neutral-200 p-5 dark:border-neutral-800">
          <Ring fraction={elapsedHours / current.target_hours}>
            <span className="text-2xl font-semibold">{formatDuration(elapsedHours)}</span>
            <span className="text-xs text-neutral-500">de {current.target_hours} h</span>
          </Ring>
          <p role="status" aria-live="polite" className="text-sm">
            {reached
              ? "¡Has llegado a tu objetivo! Puedes romper el ayuno cuando quieras."
              : `Faltan ${formatDuration(remaining)} para tu objetivo.`}
          </p>
          <p className="text-xs text-neutral-500">
            Empezó el {formatDate(current.started_at)}. Tu ventana de alimentación es de{" "}
            {current.eating_window_hours} h.
          </p>
          {current.warnings.includes("LONG_FAST_WARNING") && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Un objetivo de más de 24 h no debería hacerse sin supervisión médica.
            </p>
          )}
          <button
            type="button"
            onClick={() => void end()}
            disabled={busy}
            className="rounded-lg bg-[var(--color-primary)] px-5 py-2 text-white disabled:opacity-60"
          >
            {busy ? "…" : "Terminar ayuno"}
          </button>
        </section>
      ) : (
        <section className="flex flex-col gap-4 rounded-lg border border-neutral-200 p-5 dark:border-neutral-800">
          <h2 className="text-sm font-semibold text-neutral-500">Empezar un ayuno</h2>
          <div role="group" aria-label="Duración del ayuno" className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.hours}
                type="button"
                aria-pressed={target === p.hours}
                onClick={() => {
                  setTarget(p.hours);
                  setCustom("");
                }}
                className={`rounded-full border px-4 py-1.5 text-sm ${
                  target === p.hours
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                    : "border-neutral-300 dark:border-neutral-700"
                }`}
              >
                {p.label}
              </button>
            ))}
            <label className="flex items-center gap-2 text-sm">
              <span className="sr-only">Otra duración en horas</span>
              <input
                type="number"
                min={1}
                max={72}
                step={0.5}
                placeholder="Otra (h)"
                value={custom}
                onChange={(e) => {
                  setCustom(e.target.value);
                  if (Number(e.target.value) >= 1) setTarget(Number(e.target.value));
                }}
                className="w-24 rounded-lg border border-neutral-300 px-3 py-1.5 dark:border-neutral-700 dark:bg-neutral-900"
              />
            </label>
          </div>
          <p className="text-xs text-neutral-500">
            Ayuno de {target} h y ventana de alimentación de {Math.max(0, 24 - target)} h.
          </p>
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !(target >= 1 && target <= 72)}
            className="w-fit rounded-lg bg-[var(--color-primary)] px-5 py-2 text-white disabled:opacity-60"
          >
            {busy ? "…" : "Empezar ayuno"}
          </button>
        </section>
      )}

      {stats && stats.fasts > 0 && (
        <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Ayunos (30 días)", String(stats.fasts)],
            ["Objetivo alcanzado", `${stats.reached_target}/${stats.fasts}`],
            ["Duración media", stats.avg_hours != null ? formatDuration(stats.avg_hours) : "—"],
            ["Más largo", stats.longest_hours != null ? formatDuration(stats.longest_hours) : "—"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
              <p className="text-lg font-semibold">{value}</p>
              <p className="text-xs text-neutral-500">{label}</p>
            </div>
          ))}
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-neutral-500">Historial</h2>
        {history.length === 0 ? (
          <p className="text-sm text-neutral-500">Todavía no has terminado ningún ayuno.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {history.map((f) => (
              <li
                key={f.id}
                className="flex items-center justify-between gap-2 rounded-lg border border-neutral-200 px-3 py-2 text-sm dark:border-neutral-800"
              >
                <span>
                  {formatDate(f.started_at)} · {formatDuration(f.elapsed_hours)} de {f.target_hours} h
                </span>
                <span className="flex items-center gap-3">
                  <span className="text-xs text-neutral-500">
                    {f.reached_target ? "objetivo alcanzado" : "más corto que el objetivo"}
                  </span>
                  <button
                    type="button"
                    onClick={() => void remove(f.id)}
                    className="text-xs text-neutral-500 underline"
                    aria-label={`Eliminar el ayuno del ${formatDate(f.started_at)}`}
                  >
                    Eliminar
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
