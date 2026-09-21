/** Navegación por días del Diario. Las fechas son «AAAA-MM-DD» del calendario local del usuario. */

/** Suma `days` a una fecha ISO sin pasar por zonas horarias (se hace en mediodía UTC). */
export function shiftIsoDate(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d, 12));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** «Hoy», «Ayer», «Mañana» o «lun 14 sep» (con año si no es el de hoy). */
export function relativeDayLabel(iso: string, todayIso: string): string {
  if (iso === todayIso) return "Hoy";
  if (iso === shiftIsoDate(todayIso, -1)) return "Ayer";
  if (iso === shiftIsoDate(todayIso, 1)) return "Mañana";
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d, 12));
  const sameYear = iso.slice(0, 4) === todayIso.slice(0, 4);
  const text = date.toLocaleDateString("es-ES", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: "UTC",
  });
  return text.replace(/\./g, "");
}
