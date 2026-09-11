"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { Supplement, SupplementList } from "@/lib/types";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

const SUPPLEMENT_TYPES: { value: string; label: string }[] = [
  { value: "protein", label: "Proteína" },
  { value: "creatine", label: "Creatina" },
  { value: "magnesium", label: "Magnesio" },
  { value: "omega3", label: "Omega-3" },
  { value: "vitamin_d", label: "Vitamina D" },
  { value: "multivitamin", label: "Multivitamínico" },
  { value: "collagen", label: "Colágeno" },
  { value: "other", label: "Otro" },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Traduce "veces al día" a filas de `supplement_schedules` — una franja
 * horaria por toma, repartidas a lo largo del día y aplicadas todos los
 * días de la semana. Es la simplificación mínima necesaria para que el
 * indicador de "días de stock restantes" tenga algo con lo que estimar el
 * consumo diario; no hay editor de horarios en esta fase. */
async function createEvenlySpacedSchedules(supplementId: string, timesPerDay: number) {
  const spacingHours = Math.max(1, Math.floor(24 / timesPerDay));
  await Promise.all(
    Array.from({ length: timesPerDay }, (_, i) => {
      const hour = (8 + i * spacingHours) % 24;
      const timeOfDay = `${String(hour).padStart(2, "0")}:00:00`;
      return apiFetch(`/api/supplements/${supplementId}/schedules`, {
        method: "POST",
        body: JSON.stringify({ time_of_day: timeOfDay, days_of_week: [1, 2, 3, 4, 5, 6, 7] }),
      });
    }),
  );
}

export default function SupplementsPage() {
  const [list, setList] = useState<SupplementList | null>(null);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [type, setType] = useState("protein");
  const [otherType, setOtherType] = useState("");
  const [doseAmount, setDoseAmount] = useState("");
  const [doseUnit, setDoseUnit] = useState("g");
  const [dosesPerContainer, setDosesPerContainer] = useState("");
  const [pricePerContainer, setPricePerContainer] = useState("");
  const [timesPerDay, setTimesPerDay] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDoseAmount, setEditDoseAmount] = useState("");
  const [editDoseUnit, setEditDoseUnit] = useState("");
  const [editNotes, setEditNotes] = useState("");

  const [restockingId, setRestockingId] = useState<string | null>(null);
  const [restockAmount, setRestockAmount] = useState("");

  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeInactive]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<SupplementList>(
        `/api/supplements?include_inactive=${includeInactive}`,
      );
      setList(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    const resolvedType = type === "other" ? otherType.trim() : type;
    if (!name.trim() || !resolvedType || !doseAmount || !doseUnit.trim()) return;

    setAdding(true);
    setAddError(null);
    try {
      const created = await apiFetch<Supplement>("/api/supplements", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          type: resolvedType,
          dose_amount: Number(doseAmount),
          dose_unit: doseUnit.trim(),
          doses_per_container: dosesPerContainer ? Number(dosesPerContainer) : null,
          price_per_container: pricePerContainer ? Number(pricePerContainer) : null,
        }),
      });

      const times = timesPerDay ? Number(timesPerDay) : 0;
      if (times > 0) {
        await createEvenlySpacedSchedules(created.id, times).catch(() => {
          // el suplemento ya se creó — un fallo aquí solo deja sin estimar
          // los días de stock, no bloquea el alta
        });
      }

      setName("");
      setType("protein");
      setOtherType("");
      setDoseAmount("");
      setDoseUnit("g");
      setDosesPerContainer("");
      setPricePerContainer("");
      setTimesPerDay("");
      await load();
    } catch (err) {
      setAddError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }

  async function onLogDose(supplementId: string) {
    setRowBusy(supplementId);
    setRowError(null);
    try {
      await apiFetch(`/api/supplements/${supplementId}/log`, {
        method: "POST",
        body: JSON.stringify({ log_date: todayIso() }),
      });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  function startRestock(supplementId: string) {
    setRestockingId(supplementId);
    setRestockAmount("");
    setRowError(null);
  }

  async function onConfirmRestock(supplementId: string) {
    if (!restockAmount) return;
    setRowBusy(supplementId);
    setRowError(null);
    try {
      await apiFetch(`/api/supplements/${supplementId}/restock`, {
        method: "POST",
        body: JSON.stringify({ doses_added: Number(restockAmount) }),
      });
      setRestockingId(null);
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  function startEdit(s: Supplement) {
    setEditingId(s.id);
    setEditName(s.name);
    setEditDoseAmount(String(s.dose_amount));
    setEditDoseUnit(s.dose_unit);
    setEditNotes(s.notes ?? "");
    setRowError(null);
  }

  async function onSaveEdit(supplementId: string) {
    setRowBusy(supplementId);
    setRowError(null);
    try {
      await apiFetch(`/api/supplements/${supplementId}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editName.trim(),
          dose_amount: Number(editDoseAmount),
          dose_unit: editDoseUnit.trim(),
          notes: editNotes.trim() || null,
        }),
      });
      setEditingId(null);
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  async function onToggleActive(s: Supplement) {
    setRowBusy(s.id);
    setRowError(null);
    try {
      await apiFetch(`/api/supplements/${s.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !s.is_active }),
      });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  async function onDelete(supplementId: string) {
    if (!window.confirm("¿Eliminar este suplemento? Se borrará también su historial y stock.")) {
      return;
    }
    setRowBusy(supplementId);
    setRowError(null);
    try {
      await apiFetch(`/api/supplements/${supplementId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setRowBusy(null);
    }
  }

  return (
    <main className="flex flex-col gap-8">
      <h1 className="text-xl font-semibold">Suplementos</h1>

      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Añadir suplemento</h2>
        <form onSubmit={onAdd} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            Nombre
            <input
              type="text"
              required
              placeholder="p. ej. Creatina monohidrato"
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Tipo
            <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
              {SUPPLEMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>

          {type === "other" && (
            <label className="flex flex-col gap-1 text-sm">
              Especifica el tipo
              <input
                type="text"
                className={inputClass}
                value={otherType}
                onChange={(e) => setOtherType(e.target.value)}
              />
            </label>
          )}

          <label className="flex flex-col gap-1 text-sm">
            Dosis
            <input
              type="number"
              required
              min={0}
              step="0.01"
              className={inputClass}
              value={doseAmount}
              onChange={(e) => setDoseAmount(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Unidad
            <input
              type="text"
              required
              placeholder="g, mg, cápsulas…"
              className={inputClass}
              value={doseUnit}
              onChange={(e) => setDoseUnit(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Dosis por envase (opcional)
            <input
              type="number"
              min={1}
              className={inputClass}
              value={dosesPerContainer}
              onChange={(e) => setDosesPerContainer(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Precio por envase € (opcional)
            <input
              type="number"
              min={0}
              step="0.01"
              className={inputClass}
              value={pricePerContainer}
              onChange={(e) => setPricePerContainer(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Veces al día (opcional)
            <input
              type="number"
              min={0}
              max={10}
              placeholder="para estimar días de stock"
              className={inputClass}
              value={timesPerDay}
              onChange={(e) => setTimesPerDay(e.target.value)}
            />
          </label>

          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={adding}
              className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
            >
              {adding ? "Añadiendo…" : "Añadir suplemento"}
            </button>
          </div>
        </form>
        {addError && <p className="text-sm text-red-600">{addError}</p>}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Tus suplementos</h2>
          <label className="flex items-center gap-2 text-sm text-neutral-500">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(e) => setIncludeInactive(e.target.checked)}
            />
            Mostrar desactivados
          </label>
        </div>

        {loading && <p className="text-sm text-neutral-500">Cargando…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {rowError && <p className="mb-2 text-sm text-red-600">{rowError}</p>}

        {list && (
          <>
            {list.items.length === 0 ? (
              <p className="text-sm text-neutral-500">Todavía no has añadido ningún suplemento.</p>
            ) : (
              <ul className="flex flex-col divide-y divide-neutral-200 dark:divide-neutral-800">
                {list.items.map((s) => (
                  <li key={s.id} className="flex flex-col gap-2 py-4">
                    {editingId === s.id ? (
                      <div className="flex flex-wrap items-end gap-3">
                        <input
                          type="text"
                          className={inputClass}
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                        />
                        <input
                          type="number"
                          step="0.01"
                          className={`${inputClass} w-24`}
                          value={editDoseAmount}
                          onChange={(e) => setEditDoseAmount(e.target.value)}
                        />
                        <input
                          type="text"
                          className={`${inputClass} w-24`}
                          value={editDoseUnit}
                          onChange={(e) => setEditDoseUnit(e.target.value)}
                        />
                        <input
                          type="text"
                          placeholder="Notas"
                          className={inputClass}
                          value={editNotes}
                          onChange={(e) => setEditNotes(e.target.value)}
                        />
                        <button
                          type="button"
                          onClick={() => onSaveEdit(s.id)}
                          disabled={rowBusy === s.id}
                          className="rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-sm text-white disabled:opacity-60"
                        >
                          Guardar
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          className="text-sm text-neutral-500 underline"
                        >
                          Cancelar
                        </button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className={`text-sm font-medium ${s.is_active ? "" : "text-neutral-400"}`}>
                            {s.name}
                            {!s.is_active && " (desactivado)"}
                          </p>
                          <p className="text-xs text-neutral-500">
                            {s.type} · {s.dose_amount} {s.dose_unit}
                            {s.price_per_container != null && ` · ${s.price_per_container} €/envase`}
                          </p>
                          <p className="mt-1 text-xs">
                            {s.doses_remaining == null ? (
                              <span className="text-neutral-400">Sin control de stock</span>
                            ) : (
                              <>
                                <span className={s.low_stock ? "font-medium text-red-600" : ""}>
                                  {s.doses_remaining} dosis restantes
                                  {s.days_remaining != null && ` (≈${s.days_remaining} días)`}
                                </span>
                                {s.low_stock && (
                                  <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-red-700 dark:bg-red-950 dark:text-red-300">
                                    ¡Stock bajo!
                                  </span>
                                )}
                              </>
                            )}
                          </p>
                          {s.notes && <p className="mt-1 text-xs text-neutral-500">{s.notes}</p>}
                        </div>

                        <div className="flex flex-wrap items-center gap-3 text-sm">
                          <button
                            type="button"
                            onClick={() => onLogDose(s.id)}
                            disabled={rowBusy === s.id}
                            className="rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-white disabled:opacity-60"
                          >
                            Tomar dosis
                          </button>
                          <button
                            type="button"
                            onClick={() => startRestock(s.id)}
                            className="underline"
                          >
                            Reponer
                          </button>
                          <button type="button" onClick={() => startEdit(s)} className="underline">
                            Editar
                          </button>
                          <button
                            type="button"
                            onClick={() => onToggleActive(s)}
                            disabled={rowBusy === s.id}
                            className="text-neutral-500 underline disabled:opacity-60"
                          >
                            {s.is_active ? "Desactivar" : "Activar"}
                          </button>
                          <button
                            type="button"
                            onClick={() => onDelete(s.id)}
                            disabled={rowBusy === s.id}
                            className="text-red-600 underline disabled:opacity-60"
                          >
                            Eliminar
                          </button>
                        </div>
                      </div>
                    )}

                    {restockingId === s.id && (
                      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
                        <label className="flex flex-col gap-1 text-sm">
                          Dosis añadidas
                          <input
                            type="number"
                            min={1}
                            className={inputClass}
                            value={restockAmount}
                            onChange={(e) => setRestockAmount(e.target.value)}
                          />
                        </label>
                        <button
                          type="button"
                          onClick={() => onConfirmRestock(s.id)}
                          disabled={rowBusy === s.id || !restockAmount}
                          className="rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-sm text-white disabled:opacity-60"
                        >
                          Confirmar
                        </button>
                        <button
                          type="button"
                          onClick={() => setRestockingId(null)}
                          className="text-sm text-neutral-500 underline"
                        >
                          Cancelar
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </main>
  );
}
