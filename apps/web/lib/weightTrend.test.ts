import { describe, expect, it } from "vitest";
import {
  axisDates,
  formatKg,
  niceTicks,
  normalizePoints,
  shortDate,
  signedKg,
  totalChangeKg,
  trendKgPerWeek,
  withMovingAverage,
} from "./weightTrend";

const p = (date: string, weightKg: number) => ({ date, weightKg });

describe("normalizePoints", () => {
  it("ordena por fecha", () => {
    const out = normalizePoints([p("2026-03-02", 70), p("2026-01-05", 72)]);
    expect(out.map((x) => x.date)).toEqual(["2026-01-05", "2026-03-02"]);
  });

  it("se queda con una sola pesada por día", () => {
    const out = normalizePoints([p("2026-01-05", 72), p("2026-01-05", 71.4)]);
    expect(out).toEqual([p("2026-01-05", 71.4)]);
  });

  it("descarta valores que no son números", () => {
    const out = normalizePoints([p("2026-01-05", Number.NaN), p("2026-01-06", 70)]);
    expect(out).toEqual([p("2026-01-06", 70)]);
  });
});

describe("withMovingAverage", () => {
  it("la media de una sola pesada es esa misma pesada", () => {
    expect(withMovingAverage([p("2026-01-01", 70)])[0].averageKg).toBe(70);
  });

  it("promedia por ventana de días, no por número de pesadas", () => {
    // Dos pesadas seguidas y una un mes después: la última no debe arrastrar las viejas.
    const out = withMovingAverage([
      p("2026-01-01", 70),
      p("2026-01-02", 72),
      p("2026-03-01", 80),
    ]);
    expect(out[1].averageKg).toBe(71);
    expect(out[2].averageKg).toBe(80);
  });

  it("suaviza el ruido diario de la báscula", () => {
    const out = withMovingAverage([
      p("2026-01-01", 70),
      p("2026-01-02", 71.5),
      p("2026-01-03", 69.5),
    ]);
    expect(out[2].averageKg).toBeCloseTo(70.333, 2);
  });
});

describe("trendKgPerWeek", () => {
  it("sin dos pesadas no hay tendencia que enseñar", () => {
    expect(trendKgPerWeek([])).toBeNull();
    expect(trendKgPerWeek([p("2026-01-01", 70)])).toBeNull();
  });

  it("medio kilo en una semana es medio kilo por semana", () => {
    expect(trendKgPerWeek([p("2026-01-01", 70), p("2026-01-08", 70.5)])).toBeCloseTo(0.5, 6);
  });

  it("una bajada da pendiente negativa", () => {
    const trend = trendKgPerWeek([
      p("2026-01-01", 80),
      p("2026-01-08", 79.5),
      p("2026-01-15", 79),
    ]);
    expect(trend).toBeCloseTo(-0.5, 6);
  });

  it("dos pesadas del mismo día no dan una pendiente disparatada", () => {
    expect(trendKgPerWeek([p("2026-01-01", 70), p("2026-01-01", 71)])).toBeNull();
  });
});

describe("totalChangeKg", () => {
  it("es la diferencia entre la primera y la última", () => {
    expect(totalChangeKg([p("2026-01-01", 72), p("2026-02-01", 70.2)])).toBeCloseTo(-1.8, 6);
  });

  it("con una sola pesada no hay cambio que calcular", () => {
    expect(totalChangeKg([p("2026-01-01", 72)])).toBeNull();
  });
});

describe("niceTicks", () => {
  it("devuelve valores redondos que envuelven los datos", () => {
    const ticks = niceTicks(69.2, 72.8);
    expect(ticks[0]).toBeLessThanOrEqual(69.2);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(72.8);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });

  it("con todas las pesadas iguales sigue dando una escala usable", () => {
    const ticks = niceTicks(70, 70);
    expect(ticks.length).toBeGreaterThan(1);
    expect(ticks.some((t) => t <= 70)).toBe(true);
  });

  it("no se queda colgada con datos imposibles", () => {
    expect(niceTicks(Number.NaN, 5)).toEqual([]);
  });
});

describe("axisDates", () => {
  const many = Array.from({ length: 30 }, (_, i) =>
    p(`2026-01-${String(i + 1).padStart(2, "0")}`, 70),
  );

  it("con pocas pesadas las enseña todas", () => {
    expect(axisDates([p("2026-01-01", 70), p("2026-01-02", 70)])).toHaveLength(2);
  });

  it("con muchas reparte las etiquetas para que no se solapen", () => {
    const labels = axisDates(many, 4);
    expect(labels).toHaveLength(4);
    expect(labels[0]).toBe("2026-01-01");
    expect(labels[labels.length - 1]).toBe("2026-01-30");
  });
});

describe("formato", () => {
  it("usa la coma decimal española", () => {
    expect(formatKg(70.25)).toBe("70,3");
    expect(signedKg(-1.8)).toBe("−1,8");
    expect(signedKg(1.8)).toBe("+1,8");
    expect(signedKg(0)).toBe("0,0");
  });

  it("abrevia la fecha en español", () => {
    expect(shortDate("2026-09-12")).toBe("12 sep");
  });
});
