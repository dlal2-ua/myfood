"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import type { CurrentUser } from "@/lib/session";

export function NavBar({ user }: { user: CurrentUser | null }) {
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function onLogout() {
    setLoggingOut(true);
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } finally {
      setLoggingOut(false);
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <nav className="border-b border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-3">
        <Link href="/" className="font-semibold">
          MyFood
        </Link>
        {user ? (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <Link href="/profile">Perfil</Link>
            <Link href="/foods">Alimentos</Link>
            <Link href="/log">Registro</Link>
            <Link href="/shopping-list">Lista de la compra</Link>
            <button
              type="button"
              onClick={onLogout}
              disabled={loggingOut}
              className="text-neutral-500 underline disabled:opacity-60"
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
