"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError, errorMessage } from "@/lib/api";
import type { AiCredentialStatus, IafoodLimits } from "@/lib/types";
import { Skeleton } from "@/components/ui/states";

const inputClass =
  "rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900";

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("es-ES");
}

export default function AdminPage() {
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [credential, setCredential] = useState<AiCredentialStatus | null>(null);
  const [token, setToken] = useState("");
  const [savingToken, setSavingToken] = useState(false);

  const [limits, setLimits] = useState<IafoodLimits | null>(null);
  const [perProfileDaily, setPerProfileDaily] = useState("10");
  const [instanceDaily, setInstanceDaily] = useState("30");
  const [maxTokensPerCall, setMaxTokensPerCall] = useState("8000");
  const [savingLimits, setSavingLimits] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const [credentialRes, limitsRes] = await Promise.all([
        apiFetch<AiCredentialStatus>("/api/admin/ai/credential"),
        apiFetch<IafoodLimits>("/api/admin/ai/limits"),
      ]);
      setCredential(credentialRes);
      setLimits(limitsRes);
      setPerProfileDaily(String(limitsRes.per_profile_daily));
      setInstanceDaily(String(limitsRes.instance_daily));
      setMaxTokensPerCall(String(limitsRes.max_tokens_per_call));
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setForbidden(true);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onSaveToken(e: React.FormEvent) {
    e.preventDefault();
    setSavingToken(true);
    setError(null);
    try {
      const status = await apiFetch<AiCredentialStatus>("/api/admin/ai/credential", {
        method: "PUT",
        body: JSON.stringify({ token }),
      });
      setCredential(status);
      setToken("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingToken(false);
    }
  }

  async function onSaveLimits(e: React.FormEvent) {
    e.preventDefault();
    setSavingLimits(true);
    setError(null);
    try {
      const body: IafoodLimits = {
        per_profile_daily: Number(perProfileDaily),
        instance_daily: Number(instanceDaily),
        max_tokens_per_call: Number(maxTokensPerCall),
      };
      const saved = await apiFetch<IafoodLimits>("/api/admin/ai/limits", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setLimits(saved);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingLimits(false);
    }
  }

  if (loading) {
    return <Skeleton lines={3} />;
  }

  if (forbidden) {
    return (
      <div className="rounded-lg border border-neutral-300 p-4 text-sm dark:border-neutral-700">
        Esta sección es solo para administradores.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-xl font-semibold">Admin</h1>

      {error && (
        <p className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      <section className="flex flex-col gap-3 rounded-lg border border-neutral-300 p-4 dark:border-neutral-700">
        <h2 className="font-medium">Credencial de iafood</h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Genera el token en un dispositivo de confianza (nunca en este servidor) con{" "}
          <code className="rounded bg-neutral-100 px-1 dark:bg-neutral-800">
            claude setup-token
          </code>{" "}
          y pégalo aquí. Se guarda cifrado; nunca se vuelve a mostrar.
        </p>

        <p className="text-sm">
          Estado:{" "}
          {credential?.configured ? (
            <span className="text-green-700 dark:text-green-400">
              configurada ({credential.provider}
              {credential.updated_at ? `, actualizada ${formatDateTime(credential.updated_at)}` : ""})
            </span>
          ) : (
            <span className="text-neutral-500">no configurada</span>
          )}
        </p>

        <form onSubmit={onSaveToken} className="flex flex-col gap-2 sm:flex-row">
          <input
            type="password"
            autoComplete="off"
            placeholder="Pega aquí el setup-token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className={`${inputClass} flex-1`}
            required
          />
          <button
            type="submit"
            disabled={savingToken || token.trim().length === 0}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {savingToken ? "Guardando…" : "Guardar credencial"}
          </button>
        </form>
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-neutral-300 p-4 dark:border-neutral-700">
        <h2 className="font-medium">Límites de uso</h2>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Cuántas llamadas a la IA puede hacer cada perfil y la instancia entera por día, y el
          tope de tokens por llamada.
        </p>

        {limits && (
          <form onSubmit={onSaveLimits} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-sm">
              Por perfil al día
              <input
                type="number"
                min={1}
                value={perProfileDaily}
                onChange={(e) => setPerProfileDaily(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Por instancia al día
              <input
                type="number"
                min={1}
                value={instanceDaily}
                onChange={(e) => setInstanceDaily(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Tokens máximos por llamada
              <input
                type="number"
                min={256}
                value={maxTokensPerCall}
                onChange={(e) => setMaxTokensPerCall(e.target.value)}
                className={inputClass}
              />
            </label>
            <button
              type="submit"
              disabled={savingLimits}
              className="self-start rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              {savingLimits ? "Guardando…" : "Guardar límites"}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
