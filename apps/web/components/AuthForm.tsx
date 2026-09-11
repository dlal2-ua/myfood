"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";

type Mode = "login" | "register";

export function AuthForm({ initialMode }: { initialMode: Mode }) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const path = mode === "login" ? "/api/auth/login" : "/api/auth/register";
    const body =
      mode === "login" ? { email, password } : { email, password, display_name: displayName };

    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
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
