/** Cálculos del panel de tendencia de peso. Funciones puras y probadas: la gráfica solo
 * dibuja lo que sale de aquí.
 *
 * Nada de esto juzga si el peso sube o baja (R10): la media móvil y la pendiente están para
 * que se vea la tendencia por encima del ruido de la báscula, que oscila un kilo largo de un
 * día para otro por agua y digestión, no para dar un veredicto.
 */

export interface WeightPoint {
  date: string;
  weightKg: number;
}

export interface WeightPointWithAverage extends WeightPoint {
  /** Media móvil centrada en los últimos `days` días; `null` si no hay suficientes. */
  averageKg: number | null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function timestamp(date: string): number {
  return new Date(`${date}T00:00:00`).getTime();
}

/** Ordena por fecha y se queda con una sola pesada por día (la última que llegue). */
export function normalizePoints(points: WeightPoint[]): WeightPoint[] {
  const byDate = new Map<string, number>();
  for (const p of points) {
    if (Number.isFinite(p.weightKg)) byDate.set(p.date, p.weightKg);
  }
  return [...byDate.entries()]
    .map(([date, weightKg]) => ({ date, weightKg }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

/** Media móvil por VENTANA DE DÍAS, no por número de pesadas: quien se pesa dos veces por
 * semana y quien lo hace a diario deben ver la misma escala de tiempo suavizada. */
export function withMovingAverage(
  points: WeightPoint[],
  days = 7,
): WeightPointWithAverage[] {
  const ordered = normalizePoints(points);
  return ordered.map((point, index) => {
    const from = timestamp(point.date) - (days - 1) * DAY_MS;
    const window = ordered
      .slice(0, index + 1)
      .filter((p) => timestamp(p.date) >= from)
      .map((p) => p.weightKg);
    return {
      ...point,
      averageKg:
        window.length > 0 ? window.reduce((a, b) => a + b, 0) / window.length : null,
    };
  });
}

/** Pendiente en kg por semana por mínimos cuadrados sobre el tiempo real. Devuelve `null`
 * con menos de dos pesadas o si todas son del mismo día: una recta entre dos puntos del
 * mismo día daría una pendiente disparatada. */
export function trendKgPerWeek(points: WeightPoint[]): number | null {
  const ordered = normalizePoints(points);
  if (ordered.length < 2) return null;
  const xs = ordered.map((p) => timestamp(p.date) / DAY_MS);
  const ys = ordered.map((p) => p.weightKg);
  const meanX = xs.reduce((a, b) => a + b, 0) / xs.length;
  const meanY = ys.reduce((a, b) => a + b, 0) / ys.length;
  let numerator = 0;
  let denominator = 0;
  for (let i = 0; i < xs.length; i += 1) {
    numerator += (xs[i] - meanX) * (ys[i] - meanY);
    denominator += (xs[i] - meanX) ** 2;
  }
  if (denominator === 0) return null;
  return (numerator / denominator) * 7;
}

/** Diferencia entre la primera y la última pesada, o `null` si no hay dos. */
export function totalChangeKg(points: WeightPoint[]): number | null {
  const ordered = normalizePoints(points);
  if (ordered.length < 2) return null;
  return ordered[ordered.length - 1].weightKg - ordered[0].weightKg;
}

/** Marcas del eje vertical: valores redondos que envuelven los datos, para que la
 * cuadrícula caiga en cifras legibles (62, 62,5, 63) y no en 62,317. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = Math.max(0.5, Math.abs(min) * 0.01);
    min -= pad;
    max += pad;
  }
  const rawStep = (max - min) / Math.max(1, count - 1);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep) ?? 10 * magnitude;
  if (!Number.isFinite(step) || step <= 0) return [];
  // Se generan marcas hasta CUBRIR el máximo, no hasta acercarse: parar antes dejaba la
  // pesada más alta por encima de la última línea de la cuadrícula, fuera del área pintada.
  const ticks: number[] = [];
  for (let value = Math.floor(min / step) * step; ticks.length < 20; value += step) {
    ticks.push(Math.round(value * 1000) / 1000);
    if (value >= max) break;
  }
  return ticks;
}

const MONTHS_ES = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

/** `12 sep` — etiqueta corta de un día. */
export function shortDate(date: string): string {
  const d = new Date(`${date}T00:00:00`);
  if (Number.isNaN(d.getTime())) return date;
  return `${d.getDate()} ${MONTHS_ES[d.getMonth()]}`;
}

export function monthLabel(monthIndex: number): string {
  return MONTHS_ES[monthIndex] ?? "";
}

/** Hasta `count` fechas repartidas por el eje horizontal, siempre con la primera y la
 * última: con una etiqueta por pesada se solapan todas en cuanto hay más de diez. */
export function axisDates(points: WeightPoint[], count = 4): string[] {
  const ordered = normalizePoints(points);
  if (ordered.length <= count) return ordered.map((p) => p.date);
  const step = (ordered.length - 1) / (count - 1);
  const indexes = new Set<number>();
  for (let i = 0; i < count; i += 1) indexes.add(Math.round(i * step));
  return [...indexes].sort((a, b) => a - b).map((i) => ordered[i].date);
}

export function formatKg(value: number, digits = 1): string {
  return value.toFixed(digits).replace(".", ",");
}

export function signedKg(value: number, digits = 1): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatKg(Math.abs(value), digits)}`;
}
