"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ThemeSegmented } from "@/components/ThemeToggle";
import { useLogout } from "@/components/shell/useLogout";
import { accountItems } from "@/lib/nav";
import type { CurrentUser } from "@/lib/session";

function initialOf(name: string): string {
  return (name.trim()[0] ?? "?").toUpperCase();
}

/** Botón con la inicial del usuario que abre un menú con su cuenta, la apariencia y «Salir». */
export function AccountMenu({
  user,
  placement = "down",
  showName = false,
}: {
  user: CurrentUser;
  placement?: "down" | "up";
  showName?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const { logout, loggingOut } = useLogout(user.id);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const item =
    "flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium hover:bg-[var(--color-surface-2)]";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Cuenta de ${user.display_name}`}
        className="flex items-center gap-3 rounded-full p-0.5 text-left"
      >
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--color-primary)] text-sm font-bold text-[var(--color-on-primary)]">
          {initialOf(user.display_name)}
        </span>
        {showName && (
          <span className="min-w-0 pr-2 leading-tight">
            <span className="block truncate text-sm font-semibold">{user.display_name}</span>
            <span className="block truncate text-xs text-[var(--color-muted)]">{user.email}</span>
          </span>
        )}
      </button>
      {open && (
        <div
          role="group"
          aria-label="Menú de la cuenta"
          className={`absolute z-50 max-h-[80vh] w-64 overflow-y-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2 shadow-xl ${
            placement === "up" ? "bottom-full left-0 mb-2" : "right-0 top-full mt-2"
          }`}
        >
          <p className="px-3 pb-2 pt-1 text-xs text-[var(--color-muted)]">
            Sesión de <span className="font-semibold text-[var(--color-text)]">{user.display_name}</span>
          </p>
          {accountItems(user.role === "admin").map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className={item} onClick={() => setOpen(false)}>
              <Icon size={18} aria-hidden="true" /> {label}
            </Link>
          ))}
          <div className="my-2 px-1">
            <ThemeSegmented />
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            disabled={loggingOut}
            className={`${item} w-full text-left disabled:opacity-60`}
          >
            <LogOut size={18} aria-hidden="true" /> {loggingOut ? "Saliendo…" : "Salir"}
          </button>
        </div>
      )}
    </div>
  );
}
