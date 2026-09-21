"use client";

import { ChevronRight, LogOut, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ThemeSegmented } from "@/components/ThemeToggle";
import { useLogout } from "@/components/shell/useLogout";
import { filterGroups, visibleGroups } from "@/lib/nav";
import type { CurrentUser } from "@/lib/session";

/** Pantalla «Más»: todas las funciones de la app agrupadas y con una línea que explica cada una,
 * más un buscador para llegar a cualquiera escribiendo lo que se quiere hacer. */
export function MoreHub({ user }: { user: CurrentUser }) {
  const [query, setQuery] = useState("");
  const { logout, loggingOut } = useLogout(user.id);
  const groups = filterGroups(visibleGroups(user.role === "admin"), query);

  return (
    <main className="flex flex-col gap-6">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Más</h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">Todo lo que puedes hacer en MyFood.</p>
      </div>

      <label className="relative block">
        <span className="sr-only">Buscar una función</span>
        <Search
          size={18}
          aria-hidden="true"
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[var(--color-muted)]"
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar una función (agua, recetas, peso…)"
          className="h-12 w-full rounded-full pl-11 pr-4 text-sm shadow-[var(--shadow-card)]"
        />
      </label>

      {groups.length === 0 && (
        <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-border-strong)] p-6 text-center text-sm text-[var(--color-muted)]">
          No hay ninguna función que coincida con «{query}».
        </p>
      )}

      {groups.map((group) => (
        <section key={group.key} aria-labelledby={`grupo-${group.key}`}>
          <h2 id={`grupo-${group.key}`} className="mb-2 px-1 text-xs font-bold uppercase tracking-wider text-[var(--color-muted)]">
            {group.label}
          </h2>
          <ul className="grid gap-2.5 sm:grid-cols-2">
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className="flex min-h-[4.25rem] items-center gap-3.5 rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3 shadow-[var(--shadow-card)] transition-colors hover:border-[var(--color-primary)]"
                  >
                    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-[var(--color-primary-soft)] text-[var(--color-primary)]">
                      <Icon size={22} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-bold leading-tight">{item.label}</span>
                      <span className="mt-0.5 block text-xs leading-snug text-[var(--color-muted)]">{item.description}</span>
                    </span>
                    <ChevronRight size={18} aria-hidden="true" className="shrink-0 text-[var(--color-muted)]" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {query.trim() === "" && (
        <section aria-labelledby="grupo-apariencia" className="flex flex-col gap-3">
          <h2 id="grupo-apariencia" className="px-1 text-xs font-bold uppercase tracking-wider text-[var(--color-muted)]">
            Apariencia
          </h2>
          <ThemeSegmented />
          <button
            type="button"
            onClick={() => void logout()}
            disabled={loggingOut}
            className="mt-2 flex min-h-12 items-center justify-center gap-2 rounded-full border border-[var(--color-border-strong)] text-sm font-semibold disabled:opacity-60"
          >
            <LogOut size={18} aria-hidden="true" /> {loggingOut ? "Saliendo…" : "Cerrar sesión"}
          </button>
        </section>
      )}
    </main>
  );
}
