"use client";

import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";

type Mode = "login" | "register";

type LoginResult =
  | { mfa_required: true; mfa_token: string }
  | { id: string; email: string; display_name: string };

export function AuthForm({ initialMode }: { initialMode: Mode }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const path = mode === "login" ? "/api/auth/login" : "/api/auth/register";
    const body =
      mode === "login" ? { email, password } : { email, password, display_name: displayName };

    try {
      const result = await apiFetch<LoginResult>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if ("mfa_required" in result) {
        setMfaToken(result.mfa_token);
        return;
      }
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function onVerifyTotp(e: React.FormEvent) {
    e.preventDefault();
    if (!mfaToken) return;
    setLoading(true);
    setError(null);
    try {
      await apiFetch("/api/auth/2fa/verify-login", {
        method: "POST",
        body: JSON.stringify({ mfa_token: mfaToken, code: totpCode }),
      });
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  if (mfaToken) {
    return (
      <main className="flex flex-col items-center justify-center py-16">
        <form onSubmit={onVerifyTotp} className="flex w-full max-w-sm flex-col gap-3">
          <h1 className="mb-2 text-xl font-semibold">Verificación en dos pasos</h1>
          <p className="text-sm text-neutral-500">
            Introduce el código de 6 dígitos de tu app de autenticación.
          </p>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]{6}"
            placeholder="000000"
            required
            autoFocus
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2 text-center text-lg tracking-widest dark:border-neutral-700 dark:bg-neutral-900"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={loading || totpCode.length !== 6}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
          >
            {loading ? "Comprobando…" : "Verificar"}
          </button>
          <button
            type="button"
            onClick={() => {
              setMfaToken(null);
              setTotpCode("");
              setError(null);
            }}
            className="text-sm text-neutral-500 underline"
          >
            Volver
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="flex flex-col items-center justify-center py-16">
      <form onSubmit={onSubmit} className="flex w-full max-w-sm flex-col gap-3">
        <h1 className="mb-2 text-xl font-semibold">
          {mode === "login" ? "Iniciar sesión" : "Crear cuenta"}
        </h1>

        {mode === "register" && (
          <input
            type="text"
            placeholder="Nombre"
            required
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900"
          />
        )}
        <input
          type="email"
          placeholder="Email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900"
        />
        <input
          type="password"
          placeholder="Contraseña"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900"
        />

        {mode === "register" && (
          <>
            <MedicalDisclaimer />
            <p className="text-xs text-neutral-500">
              Tras crear la cuenta te pediremos tu consentimiento para tratar tus datos de salud
              (peso, medidas, comidas). Podrás revocarlo y borrar tu cuenta cuando quieras.
            </p>
          </>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-white disabled:opacity-60"
        >
          {loading ? "Un momento…" : mode === "login" ? "Entrar" : "Registrarme"}
        </button>

        <button
          type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="text-sm text-neutral-500 underline"
        >
          {mode === "login" ? "Crear una cuenta nueva" : "Ya tengo cuenta"}
        </button>
      </form>
    </main>
  );
}
