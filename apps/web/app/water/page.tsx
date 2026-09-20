"use client";

import { localDateIso } from "@/lib/dates";
import { useEffect, useState } from "react";
import { PushSubscribeButton } from "@/components/PushSubscribeButton";
import { useCurrentUserId } from "@/components/CurrentUser";
import { apiFetch, errorMessage } from "@/lib/api";
import { QUEUE_FLUSHED_EVENT, submitOrQueue } from "@/lib/offlineQueue";
import type { NotificationRule, WaterContainer, WaterDay, WaterSettings } from "@/lib/types";
import { ErrorState, Skeleton } from "@/components/ui/states";

const WATER_REMINDER_SCHEDULE = { times: ["10:00", "13:00", "16:00", "19:00"] };

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

function todayIso(): string {
  return localDateIso();
}

const DEFAULT_CONTAINERS: WaterContainer[] = [
  { label: "Vaso", ml: 200 },
  { label: "Botella", ml: 500 },
];

export default function WaterPage() {
  const userId = useCurrentUserId();
  const [queuedNote, setQueuedNote] = useState<string | null>(null);
  const [date] = useState(todayIso());
  const [day, setDay] = useState<WaterDay | null>(null);
  const [settings, setSettings] = useState<WaterSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [customMl, setCustomMl] = useState("");
  const [adding, setAdding] = useState(false);

  const [editingSettings, setEditingSettings] = useState(false);
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [manualTarget, setManualTarget] = useState("2500");
  const [containers, setContainers] = useState<WaterContainer[]>([]);
  const [newContainerLabel, setNewContainerLabel] = useState("");
  const [newContainerMl, setNewContainerMl] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);

  const [waterReminderRule, setWaterReminderRule] = useState<NotificationRule | null>(null);
  const [reminderBusy, setReminderBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    const containersKey = `myfood:water-containers:${userId}`;
    try {
      const [dayRes, settingsRes, rulesRes] = await Promise.all([
        apiFetch<WaterDay>(`/api/water/log?date=${date}`),
        apiFetch<WaterSettings>("/api/water/settings"),
        apiFetch<NotificationRule[]>("/api/notification-rules?kind=water"),
      ]);
      setDay(dayRes);
      setSettings(settingsRes);
      setMode(settingsRes.mode);
      setManualTarget(String(settingsRes.daily_target_ml));
      setContainers(settingsRes.containers);
      setWaterReminderRule(rulesRes[0] ?? null);
      try {
        localStorage.setItem(containersKey, JSON.stringify(settingsRes.containers));
      } catch {
        // sin almacenamiento local: solo se pierde el modo sin conexión
      }
    } catch (err) {
      setError(errorMessage(err));
      // Sin red los botones de agua siguen disponibles con los últimos contenedores conocidos.
      try {
        const saved = localStorage.getItem(containersKey);
        setContainers(saved ? (JSON.parse(saved) as WaterContainer[]) : DEFAULT_CONTAINERS);
      } catch {
        setContainers(DEFAULT_CONTAINERS);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const onFlushed = () => void load();
    window.addEventListener(QUEUE_FLUSHED_EVENT, onFlushed);
    return () => window.removeEventListener(QUEUE_FLUSHED_EVENT, onFlushed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function addMl(ml: number) {
    setAdding(true);
    setError(null);
    setQueuedNote(null);
    try {
      const outcome = await submitOrQueue({
        userId: userId ?? "",
        kind: "water",
        label: `Agua — ${ml} ml (${date})`,
        payload: { log_date: date, ml },
      });
      if (outcome.queued) {
        setQueuedNote(
          "Sin conexión: guardado en este dispositivo. Se registrará solo al volver la red.",
        );
      } else {
        await load();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }

  async function onAddCustom(e: React.FormEvent) {
    e.preventDefault();
    const ml = Number(customMl);
    if (!ml || ml <= 0) return;
    await addMl(ml);
    setCustomMl("");
  }

  async function onDelete(entryId: string) {
    try {
      await apiFetch(`/api/water/log/${entryId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function onToggleWaterReminder() {
    setReminderBusy(true);
    setError(null);
    try {
      if (waterReminderRule) {
        await apiFetch(`/api/notification-rules/${waterReminderRule.id}`, { method: "DELETE" });
        setWaterReminderRule(null);
      } else {
        const created = await apiFetch<NotificationRule>("/api/notification-rules", {
          method: "POST",
          body: JSON.stringify({ kind: "water", schedule: WATER_REMINDER_SCHEDULE }),
        });
        setWaterReminderRule(created);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setReminderBusy(false);
    }
  }

  async function onSaveSettings(e: React.FormEvent) {
    e.preventDefault();
    setSavingSettings(true);
    setError(null);
    try {
      await apiFetch("/api/water/settings", {
        method: "PUT",
        body: JSON.stringify({
          mode,
          daily_target_ml: mode === "manual" ? Number(manualTarget) : undefined,
          containers,
        }),
      });
      setEditingSettings(false);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingSettings(false);
    }
  }

  function onAddContainer() {
    const ml = Number(newContainerMl);
    if (!newContainerLabel.trim() || !ml || ml <= 0) return;
    setContainers([...containers, { label: newContainerLabel.trim(), ml }]);
    setNewContainerLabel("");
    setNewContainerMl("");
  }

  function onRemoveContainer(index: number) {
    setContainers(containers.filter((_, i) => i !== index));
  }

  if (loading) return <Skeleton lines={3} />;

  const totalMl = day?.total_ml ?? 0;
  const targetMl = day?.target_ml ?? settings?.daily_target_ml ?? 2500;
  const pct = Math.min(100, Math.round((totalMl / targetMl) * 100));

  return (
    <main className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Agua</h1>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {queuedNote && <p className="text-sm text-amber-700 dark:text-amber-300">{queuedNote}</p>}

      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-2xl font-semibold">{totalMl} ml</span>
          <span className="text-sm text-neutral-500">objetivo {targetMl} ml</span>
        </div>
        <div className="h-3 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
          <div
            className="h-full rounded-full bg-[var(--color-primary)] transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="text-sm font-semibold text-neutral-500">Recordatorios</h2>
        <PushSubscribeButton />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={waterReminderRule !== null}
            disabled={reminderBusy}
            onChange={onToggleWaterReminder}
          />
          Recordarme beber agua (10:00, 13:00, 16:00 y 19:00)
        </label>
      </section>

      <section className="flex flex-wrap items-end gap-3">
        {(settings?.containers ?? containers).map((c) => (
          <button
            key={c.label}
            type="button"
            disabled={adding}
            onClick={() => addMl(c.ml)}
            className="rounded-lg border border-neutral-300 px-4 py-2 text-sm disabled:opacity-60 dark:border-neutral-700"
          >
            + {c.label} ({c.ml} ml)
          </button>
        ))}
        <form onSubmit={onAddCustom} className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-sm">
            Cantidad (ml)
            <input
              type="number"
              min={1}
              max={5000}
              className={inputClass}
              value={customMl}
              onChange={(e) => setCustomMl(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={adding}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
          >
            Añadir
          </button>
        </form>
      </section>

      {day && day.entries.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-neutral-500">Registros de hoy</h2>
          <ul className="flex flex-col gap-1">
            {day.entries.map((entry) => (
              <li key={entry.id} className="flex items-center justify-between text-sm">
                <span>{entry.ml} ml</span>
                <button
                  type="button"
                  onClick={() => onDelete(entry.id)}
                  className="text-neutral-500 underline"
                >
                  Eliminar
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <button
          type="button"
          onClick={() => setEditingSettings(!editingSettings)}
          className="text-sm underline"
        >
          {editingSettings ? "Cerrar ajustes" : "Ajustes de objetivo y contenedores"}
        </button>

        {editingSettings && (
          <form onSubmit={onSaveSettings} className="mt-4 flex max-w-sm flex-col gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={mode === "manual"}
                onChange={(e) => setMode(e.target.checked ? "manual" : "auto")}
              />
              Fijar objetivo manualmente (si no, se calcula con tu peso y sexo)
            </label>
            {mode === "manual" && (
              <label className="flex flex-col gap-1 text-sm">
                Objetivo diario (ml)
                <input
                  type="number"
                  min={1}
                  max={10000}
                  className={inputClass}
                  value={manualTarget}
                  onChange={(e) => setManualTarget(e.target.value)}
                />
              </label>
            )}

            <div>
              <p className="mb-1 text-sm text-neutral-500">Contenedores rápidos</p>
              <ul className="mb-2 flex flex-col gap-1">
                {containers.map((c, i) => (
                  <li key={`${c.label}-${i}`} className="flex items-center justify-between text-sm">
                    <span>
                      {c.label} — {c.ml} ml
                    </span>
                    <button
                      type="button"
                      onClick={() => onRemoveContainer(i)}
                      className="text-neutral-500 underline"
                    >
                      Quitar
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex items-end gap-2">
                <label className="flex flex-col gap-1 text-sm">
                  Nombre
                  <input
                    className={inputClass}
                    value={newContainerLabel}
                    onChange={(e) => setNewContainerLabel(e.target.value)}
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  ml
                  <input
                    type="number"
                    min={1}
                    max={5000}
                    className={inputClass}
                    value={newContainerMl}
                    onChange={(e) => setNewContainerMl(e.target.value)}
                  />
                </label>
                <button
                  type="button"
                  onClick={onAddContainer}
                  className="rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700"
                >
                  Añadir
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={savingSettings}
              className="self-start rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
            >
              {savingSettings ? "Guardando…" : "Guardar ajustes"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
