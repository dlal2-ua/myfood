import { describe, expect, it } from "vitest";
import {
  buildWeeks,
  describeDay,
  intensityLevel,
  monthLabels,
  weekdayIndex,
  type HeatmapDay,
} from "./heatmap";

function range(from: string, count: number): HeatmapDay[] {
  const start = new Date(`${from}T00:00:00`);
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
    return { date: iso, count: 0 };
  });
}

describe("weekdayIndex", () => {
  it("pone el lunes arriba y el domingo abajo", () => {
    expect(weekdayIndex("2026-09-21")).toBe(0); // lunes
    expect(weekdayIndex("2026-09-27")).toBe(6); // domingo
  });
});

describe("buildWeeks", () => {
  it("sin días no hay columnas", () => {
    expect(buildWeeks([])).toEqual([]);
  });

  it("todas las columnas tienen siete celdas", () => {
    for (const weeks of [buildWeeks(range("2026-09-23", 365)), buildWeeks(range("2026-01-01", 40))]) {
      expect(weeks.every((week) => week.length === 7)).toBe(true);
    }
  });

  it("rellena el principio para que el primer día caiga en su día de la semana", () => {
    const weeks = buildWeeks(range("2026-09-23", 10)); // miércoles
    expect(weeks[0].slice(0, 2)).toEqual([null, null]);
    expect(weeks[0][2]).toMatchObject({ date: "2026-09-23" });
  });

  it("no pierde ningún día", () => {
    const days = range("2026-09-23", 365);
    const kept = buildWeeks(days).flat().filter(Boolean);
    expect(kept).toHaveLength(365);
  });
});

describe("monthLabels", () => {
  const weeks = buildWeeks(range("2025-09-22", 365));

  it("etiqueta cada mes una sola vez", () => {
    const labels = monthLabels(weeks);
    const counts = new Map<string, number>();
    for (const l of labels) counts.set(l.label, (counts.get(l.label) ?? 0) + 1);
    // Un año de columnas: cada mes aparece una vez (el de inicio puede repetirse al cerrar
    // el año, que es correcto: son dos septiembres distintos).
    expect([...counts.values()].every((n) => n <= 2)).toBe(true);
    expect(labels.length).toBeGreaterThanOrEqual(11);
  });

  it("las etiquetas van en orden y dentro del rango de columnas", () => {
    const labels = monthLabels(weeks);
    for (let i = 1; i < labels.length; i += 1) {
      expect(labels[i].weekIndex).toBeGreaterThan(labels[i - 1].weekIndex);
    }
    expect(labels[labels.length - 1].weekIndex).toBeLessThan(weeks.length);
  });

  it("no deja dos etiquetas pegadas que se leerían superpuestas", () => {
    const labels = monthLabels(weeks, 2);
    for (let i = 1; i < labels.length; i += 1) {
      expect(labels[i].weekIndex - labels[i - 1].weekIndex).toBeGreaterThanOrEqual(2);
    }
  });

  it("sin columnas no hay etiquetas", () => {
    expect(monthLabels([])).toEqual([]);
  });
});

describe("intensityLevel", () => {
  it("distingue sin actividad de poca y de mucha", () => {
    expect(intensityLevel(0)).toBe(0);
    expect(intensityLevel(1)).toBe(1);
    expect(intensityLevel(3)).toBe(2);
    expect(intensityLevel(9)).toBe(3);
  });
});

describe("describeDay", () => {
  it("dice la fecha en español y cuántos registros hubo", () => {
    expect(describeDay({ date: "2026-09-21", count: 2 })).toBe("21 sep 2026: 2 registros");
    expect(describeDay({ date: "2026-09-21", count: 1 })).toBe("21 sep 2026: 1 registro");
    expect(describeDay({ date: "2026-09-21", count: 0 })).toBe("21 sep 2026: sin registros");
  });
});
