/** Reparto del año de registro en semanas y sus etiquetas de mes.
 *
 * El mapa dibuja una columna por semana y una fila por día de la semana (lunes arriba).
 * Sin las etiquetas de mes, 52 columnas de cuadraditos no dicen en qué época del año cae
 * cada racha, que es justo lo que se quiere leer de un vistazo.
 */

export interface HeatmapDay {
  date: string;
  count: number;
}

/** Una celda vacía es un hueco de relleno al principio o al final, no un día sin registro. */
export type HeatmapCell = HeatmapDay | null;

const MONTHS_ES = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

export const WEEKDAY_INITIALS = ["L", "M", "X", "J", "V", "S", "D"];

/** `0` para lunes … `6` para domingo. Se interpreta la fecha en horario local, igual que el
 * resto de la app, no en UTC: cerca de medianoche un desfase de zona corre el día entero de
 * columna. */
export function weekdayIndex(date: string): number {
  const day = new Date(`${date}T00:00:00`).getDay(); // 0 = domingo
  return (day + 6) % 7;
}

/** Columnas de 7 celdas, de lunes a domingo, rellenando el principio de la primera semana y
 * el final de la última para que todas las columnas tengan la misma altura. */
export function buildWeeks(days: HeatmapDay[]): HeatmapCell[][] {
  if (days.length === 0) return [];
  const weeks: HeatmapCell[][] = [];
  let current: HeatmapCell[] = Array(weekdayIndex(days[0].date)).fill(null);
  for (const day of days) {
    current.push(day);
    if (current.length === 7) {
      weeks.push(current);
      current = [];
    }
  }
  if (current.length > 0) {
    weeks.push([...current, ...Array(7 - current.length).fill(null)]);
  }
  return weeks;
}

export interface MonthLabel {
  /** Índice de la columna sobre la que va la etiqueta. */
  weekIndex: number;
  label: string;
}

/** Una etiqueta por mes, sobre la primera semana que contiene un día de ese mes.
 *
 * Se descarta la etiqueta de un mes que solo asome con muy pocos días en la primera columna:
 * quedaría pegada a la del mes siguiente y se leerían las dos superpuestas. */
export function monthLabels(weeks: HeatmapCell[][], minWeeksApart = 2): MonthLabel[] {
  const labels: MonthLabel[] = [];
  let lastMonth: number | null = null;
  weeks.forEach((week, weekIndex) => {
    const firstDay = week.find((cell): cell is HeatmapDay => cell !== null);
    if (!firstDay) return;
    const month = new Date(`${firstDay.date}T00:00:00`).getMonth();
    if (month === lastMonth) return;
    lastMonth = month;
    const previous = labels[labels.length - 1];
    if (previous && weekIndex - previous.weekIndex < minWeeksApart) {
      // Demasiado cerca de la anterior: se queda la nueva, que es la del mes que domina
      // a partir de aquí.
      labels[labels.length - 1] = { weekIndex, label: MONTHS_ES[month] };
      return;
    }
    labels.push({ weekIndex, label: MONTHS_ES[month] });
  });
  return labels;
}

/** Cuántos registros hacen falta para cada nivel de intensidad. Verde neutro siempre: el
 * color dice «hubo actividad», nunca «lo hiciste bien» (R10). */
export function intensityLevel(count: number): 0 | 1 | 2 | 3 {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count <= 3) return 2;
  return 3;
}

export function describeDay(day: HeatmapDay): string {
  const d = new Date(`${day.date}T00:00:00`);
  const pretty = Number.isNaN(d.getTime())
    ? day.date
    : `${d.getDate()} ${MONTHS_ES[d.getMonth()]} ${d.getFullYear()}`;
  if (day.count === 0) return `${pretty}: sin registros`;
  return `${pretty}: ${day.count} ${day.count === 1 ? "registro" : "registros"}`;
}
