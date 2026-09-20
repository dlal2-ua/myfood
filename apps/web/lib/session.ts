import { cookies } from "next/headers";
import { API_INTERNAL_ORIGIN, SESSION_COOKIE_NAME } from "./api";

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  granted_consents: string[];
  /** Consentimientos obligatorios que faltan (R4): mientras haya alguno se bloquea el uso. */
  pending_consents: string[];
  totp_enabled: boolean;
}

/** Server-side only: reads the session cookie from the incoming request and
 * asks the API who it belongs to. Returns null when not authenticated. */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const res = await fetch(`${API_INTERNAL_ORIGIN}/api/auth/me`, {
    headers: { cookie: `${SESSION_COOKIE_NAME}=${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as CurrentUser;
}
