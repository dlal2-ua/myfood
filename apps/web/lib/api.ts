export const SESSION_COOKIE_NAME = "myfood_session";

/** Origin the Next.js *server* uses to reach the API container directly
 * (server components, route handlers). Defaults to the docker-compose
 * service name; override with API_INTERNAL_URL for local `pnpm dev`. */
export const API_INTERNAL_ORIGIN = process.env.API_INTERNAL_URL ?? "http://api:8000";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type ApiErrorBody = {
  error?: { code?: string; message?: string; details?: Record<string, unknown> };
};

async function throwApiError(res: Response): Promise<never> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    body = null;
  }
  throw new ApiError(
    res.status,
    body?.error?.code ?? "UNKNOWN_ERROR",
    body?.error?.message ?? `Error ${res.status}`,
    body?.error?.details ?? {},
  );
}

/**
 * Client-side fetch helper. Call with a relative path such as "/api/profile"
 * from "use client" components — the browser sends the request to the
 * Next.js server, which proxies it to the API (see next.config.ts rewrites),
 * and the myfood_session cookie is attached automatically.
 */
export async function apiFetch<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    await throwApiError(res);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Ha ocurrido un error inesperado.";
}
