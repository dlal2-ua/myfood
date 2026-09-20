"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

/** Rutas que siguen accesibles sin haber aceptado el consentimiento obligatorio:
 * la propia pantalla de consentimiento, la de privacidad (para ver, exportar o borrar
 * la cuenta en vez de aceptar) y las de acceso. */
const ALLOWED = ["/consent", "/privacy", "/login", "/register"];

/** Mientras falte un consentimiento obligatorio (RGPD art. 9, R4), lleva a /consent. */
export function ConsentGate({ pending }: { pending: string[] }) {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pending.length === 0) return;
    const allowed = ALLOWED.some((p) => pathname === p || pathname.startsWith(`${p}/`));
    if (!allowed && pathname !== "/") router.replace("/consent");
  }, [pending, pathname, router]);

  return null;
}
