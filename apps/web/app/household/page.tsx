"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import type { Household } from "@/lib/types";
import { ErrorState, Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

export default function HouseholdPage() {
  const [household, setHousehold] = useState<Household | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [leaving, setLeaving] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setHousehold(await apiFetch<Household | null>("/api/household"));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      setHousehold(await apiFetch<Household>("/api/household", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      }));
      setName("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function onJoin(e: React.FormEvent) {
    e.preventDefault();
    if (!inviteCode.trim()) return;
    setJoining(true);
    setError(null);
    try {
      setHousehold(
        await apiFetch<Household>("/api/household/join", {
          method: "POST",
          body: JSON.stringify({ invite_code: inviteCode.trim() }),
        }),
      );
      setInviteCode("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setJoining(false);
    }
  }

  async function onLeave() {
    setLeaving(true);
    setError(null);
    try {
      await apiFetch("/api/household/leave", { method: "POST" });
      setHousehold(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLeaving(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="text-xl font-semibold">Modo familia</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Comparte la despensa y la lista de la compra con las personas de tu hogar. El resto de
          tus datos (perfil, registro, planes...) sigue siendo privado.
        </p>
      </div>

      {loading && <Skeleton lines={3} />}
      {error && <ErrorState message={error} onRetry={() => void load()} />}

      {!loading && household && (
        <section className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
          <h2 className="text-lg font-semibold">{household.name}</h2>
          <p className="text-sm text-neutral-500">
            Código de invitación:{" "}
            <code className="rounded bg-neutral-100 px-2 py-1 tracking-widest dark:bg-neutral-900">
              {household.invite_code}
            </code>
          </p>
          <ul className="flex flex-col gap-1 text-sm">
            {household.members.map((m) => (
              <li key={m.user_id}>
                {m.display_name} <span className="text-neutral-400">· {m.email}</span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={onLeave}
            disabled={leaving}
            className="mt-2 w-fit rounded-lg border border-red-600 px-4 py-2 text-sm text-red-600 disabled:opacity-60"
          >
            {leaving ? "Saliendo…" : "Salir del hogar"}
          </button>
        </section>
      )}

      {!loading && !household && (
        <>
          <section className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
            <h2 className="text-sm font-semibold">Crear un hogar nuevo</h2>
            <form onSubmit={onCreate} className="flex flex-wrap items-end gap-3">
              <input
                type="text"
                placeholder="p. ej. Casa"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputClass}
              />
              <button
                type="submit"
                disabled={creating || !name.trim()}
                className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {creating ? "Creando…" : "Crear hogar"}
              </button>
            </form>
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
            <h2 className="text-sm font-semibold">Unirte a un hogar existente</h2>
            <form onSubmit={onJoin} className="flex flex-wrap items-end gap-3">
              <input
                type="text"
                placeholder="Código de invitación"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                className={`${inputClass} tracking-widest`}
              />
              <button
                type="submit"
                disabled={joining || !inviteCode.trim()}
                className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm text-white disabled:opacity-60"
              >
                {joining ? "Entrando…" : "Unirme"}
              </button>
            </form>
          </section>
        </>
      )}
    </main>
  );
}
