"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { clearQueue, clearUserCaches, listQueue } from "@/lib/offlineQueue";
import type { CurrentUser } from "@/lib/session";

const PRIMARY_LINKS = [
  { href: "/", label: "Hoy" },
  { href: "/log", label: "Registro" },
  { href: "/scan", label: "Escanear" },
  { href: "/diet-plans", label: "Planes" },
  { href: "/chat", label: "Chat" },
];

const MORE_LINKS = [
  { href: "/foods", label: "Alimentos" },
  { href: "/water", label: "Agua" },
  { href: "/supplements", label: "Suplementos" },
  { href: "/recordatorios", label: "Recordatorios" },
  { href: "/shopping-list", label: "Lista de la compra" },
  { href: "/pantry", label: "Despensa" },
  { href: "/recipes", label: "Recetas" },
  { href: "/progress", label: "Progreso" },
  { href: "/ayuno", label: "Ayuno" },
  { href: "/calculadoras", label: "Calculadoras" },
  { href: "/profile", label: "Perfil" },
  { href: "/household", label: "Hogar" },
  { href: "/wearables", label: "Wearables" },
  { href: "/privacy", label: "Privacidad" },
  { href: "/security", label: "Seguridad" },
];

export function NavBar({ user }: { user: CurrentUser | null }) {
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function onLogout() {
    if (user) {
      const pending = await listQueue(user.id).catch(() => []);
      if (
        pending.length > 0 &&
        !window.confirm(
          `Tienes ${pending.length} registro(s) sin sincronizar. Si sales ahora se perderán. ¿Salir igualmente?`,
        )
      ) {
        return;
      }
    }
    setLoggingOut(true);
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
      if (user) await clearQueue(user.id).catch(() => {});
      await clearUserCaches();
    } finally {
      setLoggingOut(false);
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <nav aria-label="Principal" className="border-b border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-3">
        <Link href="/" className="font-semibold">
          MyFood
        </Link>
        {user ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            {PRIMARY_LINKS.map((l) => (
              <Link key={l.href} href={l.href} className="inline-flex min-h-11 items-center">
                {l.label}
              </Link>
            ))}
            <details className="relative">
              <summary className="inline-flex min-h-11 cursor-pointer list-none items-center">
                Más ▾
              </summary>
              <ul className="absolute right-0 z-40 mt-1 grid min-w-48 gap-0 rounded-[var(--radius-card)] border border-neutral-200 bg-[var(--color-surface)] p-2 shadow-lg dark:border-neutral-800">
                {[...MORE_LINKS, ...(user.role === "admin" ? [{ href: "/admin", label: "Admin" }] : [])].map(
                  (l) => (
                    <li key={l.href}>
                      <Link href={l.href} className="flex min-h-11 items-center rounded px-2">
                        {l.label}
                      </Link>
                    </li>
                  ),
                )}
              </ul>
            </details>
            <button
              type="button"
              onClick={onLogout}
              disabled={loggingOut}
              className="min-h-11 text-neutral-500 underline disabled:opacity-60"
            >
              Salir
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-4 text-sm">
            <Link href="/login">Entrar</Link>
            <Link href="/register">Crear cuenta</Link>
          </div>
        )}
      </div>
    </nav>
  );
}
