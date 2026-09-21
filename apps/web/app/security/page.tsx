"use client";

import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";

const inputClass =
  "rounded-[var(--radius-control)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 py-2";

interface TotpSetup {
  secret: string;
  otpauth_uri: string;
}

export default function SecurityPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [settingUp, setSettingUp] = useState(false);
  const [confirmCode, setConfirmCode] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const [disablePassword, setDisablePassword] = useState("");
  const [disabling, setDisabling] = useState(false);
  const [disableError, setDisableError] = useState<string | null>(null);

  useEffect(() => {
    void loadStatus();
  }, []);

  async function loadStatus() {
    try {
      const me = await apiFetch<{ totp_enabled: boolean }>("/api/auth/me");
      setEnabled(me.totp_enabled);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }

  async function onStartSetup() {
    setSettingUp(true);
    setConfirmError(null);
    try {
      setSetup(await apiFetch<TotpSetup>("/api/auth/2fa/setup", { method: "POST" }));
    } catch (err) {
      setConfirmError(errorMessage(err));
    } finally {
      setSettingUp(false);
    }
  }

  async function onConfirm(e: React.FormEvent) {
    e.preventDefault();
    if (confirmCode.length !== 6) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      await apiFetch("/api/auth/2fa/confirm", {
        method: "POST",
        body: JSON.stringify({ code: confirmCode }),
      });
      setSetup(null);
      setConfirmCode("");
      setEnabled(true);
    } catch (err) {
      setConfirmError(errorMessage(err));
    } finally {
      setConfirming(false);
    }
  }

  async function onDisable(e: React.FormEvent) {
    e.preventDefault();
    if (!disablePassword) return;
    setDisabling(true);
    setDisableError(null);
    try {
      await apiFetch("/api/auth/2fa/disable", {
        method: "POST",
        body: JSON.stringify({ password: disablePassword }),
      });
      setEnabled(false);
      setDisablePassword("");
    } catch (err) {
      setDisableError(errorMessage(err));
    } finally {
      setDisabling(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Seguridad</h1>
      {loadError && <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>}

      {enabled === true && (
        <section className="flex flex-col gap-3">
          <p className="text-sm text-green-700 dark:text-green-400">
            La verificación en dos pasos está activada. Al iniciar sesión te pedirá además el
            código de tu app de autenticación.
          </p>
          <form onSubmit={onDisable} className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] p-4">
            <h2 className="text-sm font-semibold">Desactivar verificación en dos pasos</h2>
            <label className="flex flex-col gap-1 text-sm">
              Confirma tu contraseña
              <input
                type="password"
                className={inputClass}
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
              />
            </label>
            <button
              type="submit"
              disabled={disabling || !disablePassword}
              className="w-fit rounded-lg border border-red-600 px-4 py-2 text-sm text-red-600 dark:text-red-400 disabled:opacity-60"
            >
              {disabling ? "Desactivando…" : "Desactivar"}
            </button>
            {disableError && <p className="text-sm text-red-600 dark:text-red-400">{disableError}</p>}
          </form>
        </section>
      )}

      {enabled === false && !setup && (
        <section className="flex flex-col gap-3">
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Añade un segundo paso al iniciar sesión con una app de autenticación (Google
            Authenticator, Aegis, 1Password…).
          </p>
          <button
            type="button"
            onClick={onStartSetup}
            disabled={settingUp}
            className="w-fit rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
          >
            {settingUp ? "Generando…" : "Activar verificación en dos pasos"}
          </button>
        </section>
      )}

      {setup && (
        <section className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] p-4">
          <h2 className="text-sm font-semibold">
            1. Añade esta clave a tu app de autenticación
          </h2>
          <p className="text-sm text-neutral-500">
            Añade una cuenta nueva a mano con esta clave (no hace falta escanear nada):
          </p>
          <code className="w-fit rounded bg-neutral-100 px-3 py-2 text-sm tracking-widest dark:bg-neutral-900">
            {setup.secret}
          </code>
          <p className="break-all text-xs text-neutral-400">{setup.otpauth_uri}</p>

          <h2 className="mt-2 text-sm font-semibold">2. Confirma con el código generado</h2>
          <form onSubmit={onConfirm} className="flex items-end gap-3">
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              placeholder="000000"
              className={inputClass}
              value={confirmCode}
              onChange={(e) => setConfirmCode(e.target.value)}
            />
            <button
              type="submit"
              disabled={confirming || confirmCode.length !== 6}
              className="rounded-full bg-[var(--color-primary)] px-4 py-2 text-sm text-[var(--color-on-primary)] disabled:opacity-60 font-semibold hover:bg-[var(--color-primary-hover)]"
            >
              {confirming ? "Comprobando…" : "Confirmar"}
            </button>
          </form>
          {confirmError && <p className="text-sm text-red-600 dark:text-red-400">{confirmError}</p>}
        </section>
      )}
    </main>
  );
}
