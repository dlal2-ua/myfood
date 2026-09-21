import { describe, expect, it } from "vitest";
import {
  amountProblem,
  describeAmount,
  formatNumber,
  macrosFor,
  pluralize,
  portionForGrams,
  toGrams,
  toQuantity,
  type Portion,
} from "./portions";

const huevo: Portion = { key: "unit_egg", label: "huevo", grams: 60 };
const vaso: Portion = { key: "vaso", label: "vaso", grams: 200 };
const gramos: Portion = { key: "g", label: "gramos", grams: 1 };

describe("toGrams", () => {
  it("multiplica la cantidad por lo que pesa la ración", () => {
    expect(toGrams(2, huevo)).toBe(120);
    expect(toGrams(1.5, vaso)).toBe(300);
  });

  it("con gramos sueltos la cantidad ya son los gramos", () => {
    expect(toGrams(150, gramos)).toBe(150);
  });

  it("no registra nada con una cantidad vacía o imposible", () => {
    expect(toGrams(0, huevo)).toBe(0);
    expect(toGrams(-3, huevo)).toBe(0);
    expect(toGrams(Number.NaN, huevo)).toBe(0);
  });

  it("redondea a un decimal en vez de arrastrar la coma flotante", () => {
    expect(toGrams(0.3, { key: "cucharada", label: "cucharada", grams: 10 })).toBe(3);
    expect(toGrams(1.005, huevo)).toBe(60.3);
  });
});

describe("toQuantity", () => {
  it("convierte gramos a raciones al cambiar de medida", () => {
    expect(toQuantity(120, huevo)).toBe(2);
    expect(toQuantity(100, vaso)).toBe(0.5);
  });

  it("al pasar a gramos, la cantidad es el propio gramaje", () => {
    expect(toQuantity(137, gramos)).toBe(137);
  });
});

describe("describeAmount", () => {
  it("dice la medida y los gramos a los que equivale", () => {
    expect(describeAmount(2, huevo)).toBe("2 huevos (120 g)");
    expect(describeAmount(1, huevo)).toBe("1 huevo (60 g)");
  });

  it("con gramos sueltos no repite la cifra dos veces", () => {
    expect(describeAmount(150, gramos)).toBe("150 g");
  });

  it("acepta media ración", () => {
    expect(describeAmount(0.5, vaso)).toBe("0,5 vasos (100 g)");
  });
});

describe("pluralize", () => {
  it("pluraliza las medidas que se usan aquí", () => {
    expect(pluralize("huevo")).toBe("huevos");
    expect(pluralize("cucharada")).toBe("cucharadas");
    expect(pluralize("rebanada")).toBe("rebanadas");
  });

  it("acaba en consonante y en z", () => {
    expect(pluralize("vasos")).toBe("vasoses"); // no se usa, pero no debe reventar
    expect(pluralize("lapiz")).toBe("lapices");
  });

  it("no revienta con una etiqueta vacía", () => {
    expect(pluralize("")).toBe("");
  });
});

describe("macrosFor", () => {
  const pollo = { kcal_100g: 165, protein_100g: 31, carbs_100g: 0, fat_100g: 3.6 };

  it("escala por 100 g, igual que el API al guardar", () => {
    expect(macrosFor(pollo, 200)).toEqual({ kcal: 330, protein: 62, carbs: 0, fat: 7.2 });
  });

  it("con media ración sale la mitad", () => {
    expect(macrosFor(pollo, 50).kcal).toBe(83);
  });

  it("los valores que faltan cuentan como cero, no como NaN", () => {
    const incompleto = { kcal_100g: 100, protein_100g: null, carbs_100g: null, fat_100g: null };
    expect(macrosFor(incompleto, 100)).toEqual({ kcal: 100, protein: 0, carbs: 0, fat: 0 });
  });

  it("sin gramos no aporta nada", () => {
    expect(macrosFor(pollo, 0).kcal).toBe(0);
  });
});

describe("portionForGrams", () => {
  const portions = [huevo, gramos];

  it("elige la medida que da una cantidad redonda", () => {
    expect(portionForGrams(portions, 120).key).toBe("unit_egg");
  });

  it("si ninguna encaja, gramos sueltos", () => {
    expect(portionForGrams(portions, 137).key).toBe("g");
  });

  it("no revienta con una lista vacía", () => {
    expect(portionForGrams([], 100).key).toBe("g");
  });
});

describe("formatNumber", () => {
  it("usa la coma decimal y no rellena con ceros", () => {
    expect(formatNumber(2)).toBe("2");
    expect(formatNumber(112.5)).toBe("112,5");
    expect(formatNumber(0.25)).toBe("0,25");
  });
});

describe("amountProblem", () => {
  it("una cantidad normal no tiene ningún problema", () => {
    expect(amountProblem(150)).toBeNull();
    expect(amountProblem(5000)).toBeNull();
  });

  it("avisa y sugiere la salida cuando se pasa del tope del servidor", () => {
    // Caso real: escribir «150» pensando en gramos con la medida «filete» da 22,5 kg, y
    // antes eso solo se veía al guardar, como «Error 422».
    const problem = amountProblem(22500);
    expect(problem).toContain("22500 g");
    expect(problem).toContain("gramos");
  });

  it("no deja registrar una cantidad vacía o negativa", () => {
    expect(amountProblem(0)).not.toBeNull();
    expect(amountProblem(-5)).not.toBeNull();
    expect(amountProblem(Number.NaN)).not.toBeNull();
  });
});
