import { describe, expect, it } from "vitest";
import {
  TYPICAL_SECONDS,
  progressFraction,
  progressLabel,
  quotaIsLow,
  quotaLabel,
  remainingSeconds,
  resetLabel,
} from "./aiProgress";

describe("progressFraction", () => {
  it("empieza en cero y no vuelve nunca atrás", () => {
    expect(progressFraction(0, 12)).toBe(0);
    let previous = 0;
    for (let s = 0; s <= 60; s += 1) {
      const value = progressFraction(s, 12);
      expect(value).toBeGreaterThanOrEqual(previous);
      previous = value;
    }
  });

  it("nunca llega al 100 %, ni esperando mucho más de lo normal", () => {
    // Una barra al 100 % se lee como «ya está»: es justo lo que empuja a reenviar.
    expect(progressFraction(600, 12)).toBeLessThan(1);
    expect(progressFraction(600, 12)).toBeLessThanOrEqual(0.92);
  });

  it("va por la mitad más o menos cuando va por la mitad del tiempo típico", () => {
    const halfway = progressFraction(6, 12);
    expect(halfway).toBeGreaterThan(0.4);
    expect(halfway).toBeLessThan(0.8);
  });
});

describe("remainingSeconds", () => {
  it("cuenta hacia atrás mientras queda tiempo", () => {
    expect(remainingSeconds(0, 12)).toBe(12);
    expect(remainingSeconds(11.2, 12)).toBe(1);
  });

  it("deja de prometer un tiempo cuando ya se pasó", () => {
    expect(remainingSeconds(12, 12)).toBeNull();
    expect(remainingSeconds(40, 12)).toBeNull();
  });
});

describe("progressLabel", () => {
  it("dice cuánto queda mientras va dentro de lo normal", () => {
    expect(progressLabel(2, 12)).toBe("Quedan unos 10 segundos…");
    expect(progressLabel(11.5, 12)).toBe("Queda 1 segundo aproximadamente…");
  });

  it("al pasarse, avisa de que va lento pero que sigue en marcha", () => {
    const label = progressLabel(25, 12);
    expect(label).toContain("más de lo normal");
    expect(label).toContain("25 s");
    expect(label).toContain("Sigue en marcha");
  });
});

describe("quotaLabel", () => {
  it("usa el singular cuando queda una", () => {
    expect(quotaLabel(1, 10)).toBe("Te queda 1 de 10 hoy");
    expect(quotaLabel(4, 10)).toBe("Te quedan 4 de 10 hoy");
  });

  it("lo dice claro cuando no queda ninguna", () => {
    expect(quotaLabel(0, 10)).toBe("Sin peticiones hoy (10 al día)");
  });
});

describe("quotaIsLow", () => {
  it("avisa en el último cuarto, pero no cuando ya no queda ninguna", () => {
    expect(quotaIsLow(10, 10)).toBe(false);
    expect(quotaIsLow(3, 10)).toBe(false);
    expect(quotaIsLow(2, 10)).toBe(true);
    expect(quotaIsLow(0, 10)).toBe(false);
  });

  it("con un límite pequeño avisa al quedar la última", () => {
    expect(quotaIsLow(1, 2)).toBe(true);
    expect(quotaIsLow(2, 2)).toBe(false);
  });
});

describe("resetLabel", () => {
  it("devuelve una hora local legible", () => {
    expect(resetLabel(new Date("2026-09-21T22:00:00Z").toISOString())).toMatch(/^\d{2}:\d{2}$/);
  });

  it("no revienta con una fecha que no se entiende", () => {
    expect(resetLabel("mañana")).toBe("");
  });
});

describe("TYPICAL_SECONDS", () => {
  it("tiene una duración típica para cada tipo de petición", () => {
    for (const seconds of Object.values(TYPICAL_SECONDS)) {
      expect(seconds).toBeGreaterThan(0);
    }
  });
});
