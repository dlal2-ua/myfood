/** Cola de registros sin conexión (spec §14.4): las comidas y el agua se guardan en
 * IndexedDB cuando no hay red y se envían al recuperarla. Cada registro lleva un
 * `client_id` (UUID) que el API usa como id de la fila, así que reenviarlo —porque la
 * respuesta se perdió o porque dos pestañas sincronizan a la vez— nunca lo duplica. */
import { ApiError, apiFetch } from "@/lib/api";

export type QueueKind = "food" | "water";

export interface QueueItem {
  /** Igual que `payload.client_id`. */
  id: string;
  userId: string;
  kind: QueueKind;
  path: string;
  payload: Record<string, unknown>;
  /** Texto legible para mostrar el registro pendiente. */
  label: string;
  createdAt: number;
  status: "pending" | "rejected";
  error?: string;
}

const DB_NAME = "myfood-offline";
const STORE = "queue";
export const QUEUE_EVENT = "myfood:queue-changed";
export const QUEUE_FLUSHED_EVENT = "myfood:queue-flushed";

const LOG_PATHS: Record<QueueKind, string> = {
  food: "/api/log/food",
  water: "/api/water/log",
};

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB no disponible"));
      return;
    }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = run(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

let channel: BroadcastChannel | null = null;

function notifyChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(QUEUE_EVENT));
  try {
    channel ??= new BroadcastChannel(QUEUE_EVENT);
    channel.postMessage("changed");
  } catch {
    // BroadcastChannel no disponible: las demás pestañas se enteran al recuperar el foco.
  }
}

/** Avisa de los cambios hechos desde otras pestañas. Devuelve la función para dejar de escuchar. */
export function onQueueChanged(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(QUEUE_EVENT, listener);
  let remote: BroadcastChannel | null = null;
  try {
    remote = new BroadcastChannel(QUEUE_EVENT);
    remote.onmessage = listener;
  } catch {
    remote = null;
  }
  return () => {
    window.removeEventListener(QUEUE_EVENT, listener);
    remote?.close();
  };
}

export async function listQueue(userId: string): Promise<QueueItem[]> {
  const all = await withStore<QueueItem[]>("readonly", (s) => s.getAll());
  return all.filter((i) => i.userId === userId).sort((a, b) => a.createdAt - b.createdAt);
}

async function putItem(item: QueueItem): Promise<void> {
  await withStore("readwrite", (s) => s.put(item));
  notifyChanged();
}

export async function removeItem(id: string): Promise<void> {
  await withStore("readwrite", (s) => s.delete(id));
  notifyChanged();
}

/** Borra los pendientes de un usuario (al cerrar sesión: no deben acabar en otra cuenta). */
export async function clearQueue(userId: string): Promise<void> {
  for (const item of await listQueue(userId)) {
    await withStore("readwrite", (s) => s.delete(item.id));
  }
  notifyChanged();
}

export async function retryItem(id: string): Promise<void> {
  const item = await withStore<QueueItem | undefined>("readonly", (s) => s.get(id));
  if (!item) return;
  await putItem({ ...item, status: "pending", error: undefined });
}

/** Un fallo de red (o el servidor caído detrás del proxy) — no una respuesta del API que
 * rechaza el registro, que reintentar no arreglaría. */
export function isNetworkFailure(err: unknown): boolean {
  if (err instanceof ApiError) return [502, 503, 504].includes(err.status);
  return true;
}

export type SubmitOutcome<T> = { queued: false; result: T } | { queued: true; item: QueueItem };

interface SubmitOptions {
  userId: string;
  kind: QueueKind;
  payload: Record<string, unknown>;
  label: string;
}

/** Envía el registro y, si no hay red, lo deja en la cola para sincronizarlo después. */
export async function submitOrQueue<T>(
  opts: SubmitOptions,
  send: (path: string, body: string) => Promise<T> = (path, body) =>
    apiFetch<T>(path, { method: "POST", body }),
): Promise<SubmitOutcome<T>> {
  const clientId = crypto.randomUUID();
  const payload = { ...opts.payload, client_id: clientId };
  const path = LOG_PATHS[opts.kind];
  const item: QueueItem = {
    id: clientId,
    userId: opts.userId,
    kind: opts.kind,
    path,
    payload,
    label: opts.label,
    createdAt: Date.now(),
    status: "pending",
  };

  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    await putItem(item);
    return { queued: true, item };
  }
  try {
    return { queued: false, result: await send(path, JSON.stringify(payload)) };
  } catch (err) {
    if (!isNetworkFailure(err)) throw err;
    await putItem(item);
    return { queued: true, item };
  }
}

export interface FlushResult {
  sent: number;
  rejected: number;
  remaining: number;
  /** La sesión ha caducado: hay que volver a entrar antes de poder sincronizar. */
  needsLogin: boolean;
}

let flushing: Promise<FlushResult> | null = null;

async function flushOnce(
  userId: string,
  send: (item: QueueItem) => Promise<unknown>,
): Promise<FlushResult> {
  const result: FlushResult = { sent: 0, rejected: 0, remaining: 0, needsLogin: false };
  const items = (await listQueue(userId)).filter((i) => i.status === "pending");
  for (const item of items) {
    try {
      await send(item);
      await removeItem(item.id);
      result.sent += 1;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        result.needsLogin = true;
        break;
      }
      if (err instanceof ApiError && !isNetworkFailure(err) && err.status !== 429) {
        await putItem({ ...item, status: "rejected", error: err.message });
        result.rejected += 1;
        continue;
      }
      break; // sin red, servidor caído o límite de peticiones: se reintenta más tarde
    }
  }
  result.remaining = (await listQueue(userId)).filter((i) => i.status === "pending").length;
  return result;
}

/** Sincroniza en orden los pendientes del usuario. Una sola pasada a la vez por pestaña
 * (y entre pestañas cuando hay Web Locks); si dos coincidieran, `client_id` evita duplicados. */
export function flushQueue(
  userId: string,
  send: (item: QueueItem) => Promise<unknown> = (item) =>
    apiFetch(item.path, { method: "POST", body: JSON.stringify(item.payload) }),
): Promise<FlushResult> {
  if (flushing) return flushing;
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  const pass = (async (): Promise<FlushResult> =>
    locks
      ? await locks.request("myfood-queue-flush", () => flushOnce(userId, send))
      : await flushOnce(userId, send))();
  const tracked = pass.finally(() => {
    flushing = null;
    if (typeof window !== "undefined") window.dispatchEvent(new Event(QUEUE_FLUSHED_EVENT));
  });
  flushing = tracked;
  return tracked;
}

/** Borra las cachés del service worker que contienen datos del usuario (páginas y búsquedas). */
export async function clearUserCaches(): Promise<void> {
  if (typeof caches === "undefined") return;
  try {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((k) => k.startsWith("myfood-pages-") || k.startsWith("myfood-search-"))
        .map((k) => caches.delete(k)),
    );
  } catch {
    // Sin Cache Storage (modo privado restringido): no hay nada que borrar.
  }
}
