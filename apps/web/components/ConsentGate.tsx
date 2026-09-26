"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

/** Rutas que siguen accesibles sin haber aceptado el consentimiento obligatorio:
 * la propia pantalla de consentimiento, la de privacidad (para ver, exportar o borrar
 * la cuenta en vez de aceptar), las de acceso y el asistente de bienvenida.
 *
 * El asistente está aquí por una carrera: al aceptar el consentimiento se navega a él y se
 * refresca el layout, pero hasta que el refresco llega este componente todavía cree que hay
 * consentimientos pendientes y devolvería al usuario a la pantalla que acaba de completar.
 * Dejarlo pasar no abre ningún agujero: lo que el asistente guarda lo protege el servidor
 * (`PUT /profile` exige el consentimiento de datos de salud), no esta comprobación. */
const ALLOWED = ["/consent", "/privacy", "/login", "/register", "/bienvenida"];

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
