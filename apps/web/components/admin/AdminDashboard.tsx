"use client";

import {
  Activity,
  Check,
  Copy,
  Database,
  Sparkles,
  Ticket,
  TriangleAlert,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DailyBarsChart } from "@/components/charts";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { apiFetch, errorMessage } from "@/lib/api";
import type {
  AdminActivityDay,
  AdminAppSettings,
  AdminInvite,
  AdminOverview,
  AdminUser,
} from "@/lib/types";

const CARD =
  "rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 shadow-[var(--shadow-card)]";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });
}

function Metric({
  icon: Icon,
  label,
  value,
  hint,
  warn,
}: {
  icon: typeof Users;
  label: string;
  value: string;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <div className={CARD}>
      <p className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-muted)]">
        <Icon size={14} aria-hidden="true" />
        {label}
      </p>
      <p
        className={`mt-1 text-2xl font-extrabold tracking-tight ${
          warn ? "text-amber-700 dark:text-amber-300" : ""
        }`}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-[var(--color-muted)]">{hint}</p>}
    </div>
  );
}

/** Interruptor con su etiqueta. Se bloquea mientras se guarda para no mandar dos cambios
 * seguidos del mismo valor. */
function Toggle({
  on,
  onChange,
  label,
  busy,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  label: string;
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={busy}
      onClick={() => onChange(!on)}
      className={`inline-flex h-7 w-12 shrink-0 items-center rounded-full p-0.5 transition-colors disabled:opacity-50 ${
        on ? "bg-[var(--color-primary)]" : "bg-[var(--color-border-strong)]"
      }`}
    >
      <span
        aria-hidden="true"
        className={`grid h-6 w-6 place-items-center rounded-full bg-white text-[var(--color-primary)] shadow transition-transform ${
          on ? "translate-x-5" : ""
        }`}
      >
        {on ? <Check size={13} /> : <X size={13} className="text-[var(--color-muted)]" />}
      </span>
    </button>
  );
}

function UsersTable({ users, onPatch }: { users: AdminUser[]; onPatch: (id: string, patch: Record<string, boolean>) => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);

  async function patch(id: string, patchBody: Record<string, boolean>) {
    setBusy(id);
    try {
      await onPatch(id, patchBody);
    } finally {
      setBusy(null);
    }
  }

  return (
    <ul className="flex flex-col gap-2">
      {users.map((u) => (
        <li
          key={u.id}
          className={`${CARD} flex flex-wrap items-center gap-x-4 gap-y-2 ${
            u.is_active ? "" : "opacity-60"
          }`}
        >
          <div className="min-w-[10rem] flex-1">
            <p className="flex flex-wrap items-center gap-2 text-sm font-bold">
              {u.display_name}
              {u.role === "admin" && (
                <span className="rounded-full bg-[var(--color-primary-soft)] px-2 py-0.5 text-[11px] text-[var(--color-primary)]">
                  admin
                </span>
              )}
              {!u.is_active && (
                <span className="rounded-full bg-[var(--color-surface-2)] px-2 py-0.5 text-[11px] text-[var(--color-muted)]">
                  desactivada
                </span>
              )}
            </p>
            <p className="truncate text-xs text-[var(--color-muted)]">{u.email}</p>
            <p className="mt-0.5 text-xs text-[var(--color-muted)]">
              Alta {fmtDate(u.created_at)} · Última entrada {fmtDate(u.last_seen_at)} ·{" "}
              {u.logging_days} {u.logging_days === 1 ? "día" : "días"} registrando
              {u.invited_with ? ` · invitación ${u.invited_with}` : ""}
            </p>
          </div>

          <div className="text-center">
            <p className="text-xs text-[var(--color-muted)]">IA hoy</p>
            <p className="text-sm font-bold">{u.ai_used_today}</p>
            <p className="text-[11px] text-[var(--color-muted)]">{u.ai_used_30d} en 30 d</p>
          </div>

          <div className="flex items-center gap-4">
            <label className="flex flex-col items-center gap-1 text-[11px] font-semibold text-[var(--color-muted)]">
              IA
              <Toggle
                on={u.ai_enabled}
                busy={busy === u.id}
                label={`Permitir la IA a ${u.display_name}`}
                onChange={(next) => void patch(u.id, { ai_enabled: next })}
              />
            </label>
            <label className="flex flex-col items-center gap-1 text-[11px] font-semibold text-[var(--color-muted)]">
              Acceso
              <Toggle
                on={u.is_active}
                busy={busy === u.id}
                label={`Permitir el acceso a ${u.display_name}`}
                onChange={(next) => void patch(u.id, { is_active: next })}
              />
            </label>
          </div>
        </li>
      ))}
    </ul>
  );
}

function InvitesCard({
  invites,
  onCreate,
  onRevoke,
}: {
  invites: AdminInvite[];
  onCreate: (note: string) => Promise<string>;
  onRevoke: (code: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    try {
      const code = await onCreate(note);
      setNote("");
      await copy(code);
    } finally {
      setBusy(false);
    }
  }

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(code);
      setTimeout(() => setCopied(null), 2500);
    } catch {
      // Sin portapapeles (navegador antiguo o sin permiso): el código está a la vista.
    }
  }

  const open = invites.filter((i) => i.status === "disponible");
  const rest = invites.filter((i) => i.status !== "disponible");

  return (
    <section className={`${CARD} flex flex-col gap-3`}>
      <div>
        <h2 className="text-lg font-extrabold tracking-tight">Invitaciones</h2>
        <p className="text-xs text-[var(--color-muted)]">
          Cada código sirve para una sola cuenta. Al generarlo se copia al portapapeles.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          type="text"
          value={note}
          maxLength={80}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Para quién es (opcional)"
          className="h-11 min-w-[12rem] flex-1 rounded-[var(--radius-control)] px-3 text-sm"
        />
        <button
          type="button"
          onClick={() => void create()}
          disabled={busy}
          className="min-h-11 rounded-full bg-[var(--color-primary)] px-5 text-sm font-bold text-[var(--color-on-primary)] disabled:opacity-60"
        >
          {busy ? "Generando…" : "Generar código"}
        </button>
      </div>

      {open.length === 0 && rest.length === 0 && (
        <p className="text-sm text-[var(--color-muted)]">
          Todavía no hay códigos. Genera uno para invitar a alguien.
        </p>
      )}

      {open.length > 0 && (
        <ul className="flex flex-col gap-2">
          {open.map((i) => (
            <li
              key={i.code}
              className="flex flex-wrap items-center gap-2 rounded-[var(--radius-card)] bg-[var(--color-surface-2)] px-3 py-2"
            >
              <code className="font-mono text-sm font-bold tracking-widest">{i.code}</code>
              {i.note && <span className="text-xs text-[var(--color-muted)]">{i.note}</span>}
              <span className="ml-auto flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => void copy(i.code)}
                  aria-label={`Copiar el código ${i.code}`}
                  className="grid h-9 w-9 place-items-center rounded-full text-[var(--color-muted)] hover:bg-[var(--color-surface)]"
                >
                  {copied === i.code ? <Check size={15} /> : <Copy size={15} />}
                </button>
                <button
                  type="button"
                  onClick={() => void onRevoke(i.code)}
                  className="min-h-9 rounded-full px-3 text-xs font-semibold text-[var(--color-muted)] underline"
                >
                  Anular
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {rest.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-semibold text-[var(--color-muted)]">
            Ver los {rest.length} códigos usados o anulados
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {rest.map((i) => (
              <li key={i.code} className="flex flex-wrap items-center gap-2 text-xs">
                <code className="font-mono tracking-widest text-[var(--color-muted)]">{i.code}</code>
                <span className="text-[var(--color-muted)]">
                  {i.status === "usado"
                    ? `usado por ${i.used_by_name ?? "alguien"} el ${fmtDate(i.used_at)}`
                    : `anulado el ${fmtDate(i.revoked_at)}`}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Panel del administrador: quién tiene cuenta, quién puede usar la IA y cuánto gasta,
 * cómo se usa la app y cómo está la instancia. Nunca enseña lo que ha comido nadie. */
export function AdminDashboard() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [invites, setInvites] = useState<AdminInvite[]>([]);
  const [activity, setActivity] = useState<AdminActivityDay[]>([]);
  const [settings, setSettings] = useState<AdminAppSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, u, i, a, s] = await Promise.all([
        apiFetch<AdminOverview>("/api/admin/overview"),
        apiFetch<AdminUser[]>("/api/admin/users"),
        apiFetch<AdminInvite[]>("/api/admin/invites"),
        apiFetch<AdminActivityDay[]>("/api/admin/activity?days=30"),
        apiFetch<AdminAppSettings>("/api/admin/settings"),
      ]);
      setOverview(o);
      setUsers(u);
      setInvites(i);
      setActivity(a);
      setSettings(s);
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

  async function patchUser(id: string, patch: Record<string, boolean>) {
    try {
      const updated = await apiFetch<AdminUser>(`/api/admin/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setUsers((prev) => prev.map((u) => (u.id === id ? updated : u)));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveSettings(patch: Partial<AdminAppSettings>) {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    try {
      await apiFetch("/api/admin/settings", { method: "PUT", body: JSON.stringify(next) });
    } catch (err) {
      setSettings(settings);
      setError(errorMessage(err));
    }
  }

  if (loading && !overview) return <Skeleton lines={8} />;
  if (error && !overview) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <div className="flex flex-col gap-6">
      {error && <ErrorState message={error} onRetry={() => void load()} />}

      {overview && (
        <>
          <section aria-label="Resumen" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric
              icon={Users}
              label="Cuentas"
              value={String(overview.users_total)}
              hint={`${overview.users_active} activas · ${overview.new_users_30d} nuevas en 30 d`}
            />
            <Metric
              icon={Sparkles}
              label="Con IA permitida"
              value={String(overview.users_with_ai)}
              hint={`${overview.ai_used_today}/${overview.ai_instance_limit} peticiones hoy en la casa`}
              warn={overview.ai_used_today >= overview.ai_instance_limit}
            />
            <Metric
              icon={Activity}
              label="Registrando esta semana"
              value={String(overview.users_logging_last_7d)}
              hint={`${overview.food_entries_today} comidas hoy · ${overview.food_entries_7d} en 7 días`}
            />
            <Metric
              icon={Ticket}
              label="Códigos sin usar"
              value={String(overview.invites_usable)}
              hint={overview.invite_only ? "Registro por invitación" : "Registro abierto"}
              warn={overview.invite_only && overview.invites_usable === 0}
            />
          </section>

          <section className={CARD}>
            <h2 className="mb-1 text-lg font-extrabold tracking-tight">Actividad</h2>
            <p className="mb-3 text-xs text-[var(--color-muted)]">
              Comidas registradas al día en toda la instancia, últimos 30 días.
            </p>
            <DailyBarsChart
              data={activity.map((d) => ({ date: d.date, value: d.entries }))}
              unit=" registros"
            />
          </section>

          <section className="grid gap-3 md:grid-cols-2">
            <div className={CARD}>
              <h2 className="mb-2 text-lg font-extrabold tracking-tight">Gasto de IA</h2>
              <dl className="flex flex-col gap-1.5 text-sm">
                {[
                  ["Peticiones hoy en la casa", `${overview.ai_used_today} de ${overview.ai_instance_limit}`],
                  ["Sesiones en 30 días", String(overview.ai_sessions_30d)],
                  ["Fallidas en 7 días", String(overview.ai_failed_7d)],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <dt className="text-[var(--color-muted)]">{label}</dt>
                    <dd className="font-bold">{value}</dd>
                  </div>
                ))}
              </dl>
              {overview.ai_failed_7d > 0 && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-300">
                  <TriangleAlert size={13} aria-hidden="true" className="mt-px shrink-0" />
                  Hay peticiones que no llegaron a terminar. Revisa el registro del worker.
                </p>
              )}
            </div>

            <div className={CARD}>
              <h2 className="mb-2 flex items-center gap-1.5 text-lg font-extrabold tracking-tight">
                <Database size={16} aria-hidden="true" /> Instancia
              </h2>
              <dl className="flex flex-col gap-1.5 text-sm">
                {[
                  ["Alimentos en el catálogo", overview.foods_total.toLocaleString("es-ES")],
                  ["Tamaño de la base de datos", overview.database_size],
                  ["Último alimento incorporado", fmtDate(overview.last_food_ingested_at)],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <dt className="text-[var(--color-muted)]">{label}</dt>
                    <dd className="font-bold">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>

          {overview.top_foods_7d.length > 0 && (
            <section className={CARD}>
              <h2 className="mb-2 text-lg font-extrabold tracking-tight">
                Lo más registrado esta semana
              </h2>
              <ol className="flex flex-col gap-1 text-sm">
                {overview.top_foods_7d.map((f, i) => (
                  <li key={f.name} className="flex justify-between gap-3">
                    <span className="truncate">
                      {i + 1}. {f.name}
                    </span>
                    <span className="shrink-0 font-bold">{f.uses}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}

      {settings && (
        <section className={`${CARD} flex flex-col gap-3`}>
          <h2 className="text-lg font-extrabold tracking-tight">Quién puede entrar</h2>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-[14rem] flex-1">
              <p className="text-sm font-bold">Registro solo con invitación</p>
              <p className="text-xs text-[var(--color-muted)]">
                Con esto apagado, cualquiera con la dirección de la app puede crearse una cuenta.
              </p>
            </div>
            <Toggle
              on={settings.invite_only}
              label="Registro solo con invitación"
              onChange={(next) => void saveSettings({ invite_only: next })}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-[14rem] flex-1">
              <p className="text-sm font-bold">Las cuentas nuevas pueden usar la IA</p>
              <p className="text-xs text-[var(--color-muted)]">
                Apagado, cada cuenta nueva nace sin IA y se la habilitas tú desde la lista.
              </p>
            </div>
            <Toggle
              on={settings.ai_enabled_by_default}
              label="Las cuentas nuevas pueden usar la IA"
              onChange={(next) => void saveSettings({ ai_enabled_by_default: next })}
            />
          </div>
        </section>
      )}

      <InvitesCard
        invites={invites}
        onCreate={async (note) => {
          const created = await apiFetch<AdminInvite>("/api/admin/invites", {
            method: "POST",
            body: JSON.stringify({ note: note || null }),
          });
          setInvites((prev) => [created, ...prev]);
          return created.code;
        }}
        onRevoke={async (code) => {
          await apiFetch(`/api/admin/invites/${code}`, { method: "DELETE" });
          setInvites((prev) =>
            prev.map((i) =>
              i.code === code
                ? { ...i, status: "revocado", revoked_at: new Date().toISOString() }
                : i,
            ),
          );
        }}
      />

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-lg font-extrabold tracking-tight">Cuentas</h2>
          <p className="text-xs text-[var(--color-muted)]">
            «IA» deja usar a Claude (es lo que gasta cuota). «Acceso» deja entrar en la app.
            Aquí no se ve lo que ha comido nadie.
          </p>
        </div>
        <UsersTable users={users} onPatch={patchUser} />
      </section>
    </div>
  );
}
