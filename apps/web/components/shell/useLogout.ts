"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiFetch } from "@/lib/api";
import { clearQueue, clearUserCaches, listQueue } from "@/lib/offlineQueue";

/** Cierra la sesión. Si quedan registros sin sincronizar avisa antes: al salir se borran de este
 * dispositivo. */
export function useLogout(userId: string | null) {
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  async function logout() {
    if (userId) {
      const pending = await listQueue(userId).catch(() => []);
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
      if (userId) await clearQueue(userId).catch(() => {});
      await clearUserCaches();
    } finally {
      setLoggingOut(false);
      router.push("/login");
      router.refresh();
    }
  }

  return { logout, loggingOut };
}
