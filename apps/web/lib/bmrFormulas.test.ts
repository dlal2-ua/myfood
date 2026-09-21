import { describe, expect, it } from "vitest";
import {
  BMR_FORMULAS,
  formulaInfo,
  isUnavailable,
  recommendationReason,
  recommendedFormula,
} from "./bmrFormulas";

describe("BMR_FORMULAS", () => {
  it("ofrece las cuatro que acepta el API", () => {
    expect(BMR_FORMULAS.map((f) => f.key)).toEqual([
      "mifflin",
      "katch",
      "cunningham",
      "harris",
    ]);
  });

  it("cada una explica qué hace y qué datos necesita", () => {
    for (const f of BMR_FORMULAS) {
      expect(f.description.length).toBeGreaterThan(40);
      expect(f.needs).toBeTruthy();
    }
  });

  it("solo las de masa magra piden el %grasa", () => {
    expect(formulaInfo("katch").needsBodyFat).toBe(true);
    expect(formulaInfo("cunningham").needsBodyFat).toBe(true);
    expect(formulaInfo("mifflin").needsBodyFat).toBe(false);
    expect(formulaInfo("harris").needsBodyFat).toBe(false);
  });
});

describe("recommendedFormula", () => {
  it("sin %grasa recomienda la general más contrastada", () => {
    expect(recommendedFormula(false)).toBe("mifflin");
  });

  it("con %grasa recomienda la que parte de la masa magra", () => {
    expect(recommendedFormula(true)).toBe("katch");
  });

  it("la recomendada siempre se puede calcular con los datos que hay", () => {
    for (const hasBodyFat of [true, false]) {
      expect(isUnavailable(recommendedFormula(hasBodyFat), hasBodyFat)).toBe(false);
    }
  });
});

describe("recommendationReason", () => {
  it("sin %grasa explica cómo mejorar la estimación", () => {
    expect(recommendationReason(false)).toContain("Katch-McArdle");
  });

  it("con %grasa explica de dónde sale la precisión", () => {
    expect(recommendationReason(true)).toContain("masa magra");
  });
});

describe("isUnavailable", () => {
  it("avisa de que Katch y Cunningham no salen sin %grasa", () => {
    expect(isUnavailable("katch", false)).toBe(true);
    expect(isUnavailable("cunningham", false)).toBe(true);
    expect(isUnavailable("katch", true)).toBe(false);
  });

  it("las generales siempre están disponibles", () => {
    expect(isUnavailable("mifflin", false)).toBe(false);
    expect(isUnavailable("harris", false)).toBe(false);
  });
});
