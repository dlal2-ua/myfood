/** Cómo se cuenta lo que tarda una petición a iafood, para poder enseñarlo por pantalla.
 *
 * No hay forma de saber de antemano cuánto tardará el modelo, así que la barra no miente:
 * avanza contra una duración TÍPICA medida en producción y se frena antes de llenarse.
 * Pasada esa duración deja de prometer un tiempo y solo dice que va lento — preferible a
 * una barra que llega al 100 % y se queda ahí, que es lo que empuja a volver a pulsar.
 */

/** Segundos que tarda normalmente cada tipo de petición (medido en producción). */
export const TYPICAL_SECONDS = {
  /** Interpretar un texto de comida: una llamada con búsqueda en el catálogo. */
  smart_log: 12,
  /** Un turno de chat: unos 5 s sin herramientas, más si tiene que consultar tu día. */
  chat: 10,
} as const;

export type AiTask = keyof typeof TYPICAL_SECONDS;

/** Hasta dónde llega la barra mientras sigue esperando: nunca el 100 %, porque el 100 %
 * se lee como «ya está» y solo terminamos cuando llega la respuesta de verdad. */
const MAX_FRACTION = 0.92;

export function progressFraction(elapsedSeconds: number, typicalSeconds: number): number {
  if (typicalSeconds <= 0) return MAX_FRACTION;
  const raw = elapsedSeconds / typicalSeconds;
  // Se acerca a MAX_FRACTION sin alcanzarlo: rápido al principio, cada vez más lento.
  return Math.min(MAX_FRACTION, MAX_FRACTION * (1 - Math.exp(-2.2 * raw)));
}

/** Segundos que quedan según lo que tarda normalmente, o `null` si ya se pasó de ahí. */
export function remainingSeconds(
  elapsedSeconds: number,
  typicalSeconds: number,
): number | null {
  const left = Math.ceil(typicalSeconds - elapsedSeconds);
  return left > 0 ? left : null;
}

export function progressLabel(elapsedSeconds: number, typicalSeconds: number): string {
  const left = remainingSeconds(elapsedSeconds, typicalSeconds);
  if (left === null) {
    return `Está tardando más de lo normal — ${Math.round(elapsedSeconds)} s esperando. Sigue en marcha.`;
  }
  if (left === 1) return "Queda 1 segundo aproximadamente…";
  return `Quedan unos ${left} segundos…`;
}

/** Cómo se dice cuántas peticiones quedan hoy, y si conviene ir con cuidado. */
export function quotaLabel(remaining: number, limit: number): string {
  if (remaining <= 0) return `Sin peticiones hoy (${limit} al día)`;
  if (remaining === 1) return `Te queda 1 de ${limit} hoy`;
  return `Te quedan ${remaining} de ${limit} hoy`;
}

export function quotaIsLow(remaining: number, limit: number): boolean {
  return remaining > 0 && remaining <= Math.max(1, Math.floor(limit * 0.25));
}

/** La hora local a la que se reinicia la cuota, tal como se enseña al usuario. */
export function resetLabel(resetAtIso: string): string {
  const at = new Date(resetAtIso);
  if (Number.isNaN(at.getTime())) return "";
  return at.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}
