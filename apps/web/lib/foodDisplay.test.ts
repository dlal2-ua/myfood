import { describe, expect, it } from "vitest";
import { brandLabel, grams } from "@/lib/foodDisplay";

describe("brandLabel", () => {
  it("shows the first brand of the list", () => {
    expect(brandLabel("Milbona, Lidl")).toBe("Milbona");
    expect(brandLabel("Hacendado, MERCADONA", "Mercadona")).toBe("Hacendado");
  });
  it("does not repeat the supermarket's own name", () => {
    expect(brandLabel("Lidl", "Lidl")).toBeNull();
    expect(brandLabel("MERCADONA", "Mercadona")).toBeNull();
  });
  it("handles missing brands", () => {
    expect(brandLabel(null)).toBeNull();
    expect(brandLabel("")).toBeNull();
    expect(brandLabel(" , Lidl")).toBeNull();
  });
});

describe("grams", () => {
  it("drops useless decimals", () => {
    expect(grams(23)).toBe("23 g");
    expect(grams(3.64)).toBe("3.6 g");
    expect(grams(0)).toBe("0 g");
    expect(grams(null)).toBe("—");
  });
});
