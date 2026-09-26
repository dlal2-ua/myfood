"use client";

import { Logo } from "@/components/Logo";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch, errorMessage } from "@/lib/api";
import { clearUserCaches } from "@/lib/offlineQueue";

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
  const [inviteCode, setInviteCode] = useState("");
  // La app está abierta a internet: si la instancia es «solo con invitación», registrarse
  // exige un código que da el administrador.
  const [inviteOnly, setInviteOnly] = useState(false);

  useEffect(() => {
    apiFetch<{ invite_only: boolean }>("/api/auth/config")
      .then((c) => setInviteOnly(c.invite_only))
      .catch(() => {
        // Si no se puede consultar, el servidor lo exigirá igualmente al registrarse.
      });
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const path = mode === "login" ? "/api/auth/login" : "/api/auth/register";
    const body =
      mode === "login"
        ? { email, password }
        : { email, password, display_name: displayName, invite_code: inviteCode.trim() };

    try {
      const result = await apiFetch<LoginResult>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if ("mfa_required" in result) {
        setMfaToken(result.mfa_token);
        return;
      }
      await clearUserCaches();
      // Quien acaba de registrarse va al consentimiento —que es lo que este formulario le
      // promete— y de ahí al asistente; quien entra, a su día. Antes caía en «/» con los
      // consentimientos pendientes y solo se le rebotaba a «/consent» al intentar moverse.
      router.push(mode === "register" ? "/consent" : "/");
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
      await clearUserCaches();
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  const field =
    "h-12 w-full rounded-2xl px-4 text-[15px] focus-visible:outline-2";
  const primary =
    "flex min-h-12 items-center justify-center rounded-full bg-[var(--color-primary)] px-5 text-[15px] font-bold text-[var(--color-on-primary)] shadow-sm transition-colors hover:bg-[var(--color-primary-hover)] disabled:opacity-60";

  if (mfaToken) {
    return (
      <AuthCard title="Verificación en dos pasos" subtitle="Introduce el código de 6 dígitos de tu app de autenticación.">
        <form onSubmit={onVerifyTotp} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-sm font-semibold">
            Código
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]{6}"
              placeholder="000000"
              required
              autoFocus
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value)}
              className={`${field} text-center text-xl tracking-[0.4em]`}
            />
          </label>
          {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <button type="submit" disabled={loading || totpCode.length !== 6} className={primary}>
            {loading ? "Comprobando…" : "Verificar"}
          </button>
          <button
            type="button"
            onClick={() => {
              setMfaToken(null);
              setTotpCode("");
              setError(null);
            }}
            className="min-h-11 text-sm font-semibold text-[var(--color-muted)]"
          >
            Volver
          </button>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={mode === "login" ? "Te damos la bienvenida" : "Crea tu cuenta"}
      subtitle={
        mode === "login"
          ? "Entra para ver tu día, tu dieta y tu progreso."
          : "Empieza a registrar lo que comes en menos de un minuto."
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3.5">
        {mode === "register" && (
          <label className="flex flex-col gap-1.5 text-sm font-semibold">
            Nombre
            <input
              type="text"
              autoComplete="given-name"
              required
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className={field}
            />
          </label>
        )}
        <label className="flex flex-col gap-1.5 text-sm font-semibold">
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={field}
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-semibold">
          Contraseña
          <input
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={field}
          />
          {mode === "register" && (
            <span className="text-xs font-normal text-[var(--color-muted)]">Mínimo 8 caracteres.</span>
          )}
        </label>

        {mode === "register" && inviteOnly && (
          <label className="flex flex-col gap-1.5 text-sm font-semibold">
            Código de invitación
            <input
              type="text"
              required
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="XXXXX-XXXXX"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
              className={`${field} tracking-widest`}
            />
            <span className="text-xs font-normal text-[var(--color-muted)]">
              Esta app es por invitación. Pídele un código a quien la administra.
            </span>
          </label>
        )}

        {mode === "register" && (
          <>
            <MedicalDisclaimer />
            <p className="text-xs text-[var(--color-muted)]">
              Tras crear la cuenta te pediremos tu consentimiento para tratar tus datos de salud
              (peso, medidas, comidas). Podrás revocarlo y borrar tu cuenta cuando quieras.
            </p>
          </>
        )}

        {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}

        <button type="submit" disabled={loading} className={primary}>
          {loading ? "Un momento…" : mode === "login" ? "Entrar" : "Registrarme"}
        </button>

        <button
          type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="min-h-11 rounded-full bg-[var(--color-primary-soft)] text-sm font-bold text-[var(--color-primary)]"
        >
          {mode === "login" ? "Crear una cuenta nueva" : "Ya tengo cuenta"}
        </button>
      </form>
    </AuthCard>
  );
}

function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="flex justify-center px-4 pb-16 pt-6">
      <div className="w-full max-w-md rounded-[28px] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-card)] sm:p-8">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <Logo size={52} showName={false} />
          <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
          <p className="text-sm text-[var(--color-muted)]">{subtitle}</p>
        </div>
        {children}
      </div>
    </main>
  );
}
