/** Fecha local (YYYY-MM-DD) del dispositivo. `toISOString()` da la fecha UTC, que entre las
 * 00:00 y las 02:00 de España sigue siendo «ayer» y registraría la comida en el día anterior. */
export function localDateIso(date: Date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
