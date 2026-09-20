"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { clearQueue, clearUserCaches, listQueue } from "@/lib/offlineQueue";
import type { CurrentUser } from "@/lib/session";

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
    <nav className="border-b border-neutral-200 dark:border-neutral-800">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-3">
        <Link href="/" className="font-semibold">
          MyFood
        </Link>
        {user ? (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <Link href="/profile">Perfil</Link>
            <Link href="/foods">Alimentos</Link>
            <Link href="/scan">Escanear</Link>
            <Link href="/log">Registro</Link>
            <Link href="/chat">Chat</Link>
            <Link href="/water">Agua</Link>
            <Link href="/shopping-list">Lista de la compra</Link>
            <Link href="/pantry">Despensa</Link>
            <Link href="/household">Hogar</Link>
            <Link href="/progress">Progreso</Link>
            <Link href="/ayuno">Ayuno</Link>
            <Link href="/calculadoras">Calculadoras</Link>
            <Link href="/supplements">Suplementos</Link>
            <Link href="/recordatorios">Recordatorios</Link>
            <Link href="/diet-plans">Planes</Link>
            <Link href="/recipes">Recetas</Link>
            <Link href="/wearables">Wearables</Link>
            <Link href="/privacy">Privacidad</Link>
            <Link href="/security">Seguridad</Link>
            {user.role === "admin" && <Link href="/admin">Admin</Link>}
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
