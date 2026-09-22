import { describe, expect, it } from "vitest";
import {
  activeChips,
  activeCount,
  emptyFilters,
  fromUrlParams,
  toUrlParams,
  hasCriteria,
  toSearchQuery,
  toggleOption,
  visibleOptions,
} from "@/lib/foodFilters";
import type { FoodFacets } from "@/lib/types";

const facets: FoodFacets = {
  supermarket: [
    { code: "lidl", label: "Lidl", count: 12 },
    { code: "aldi", label: "Aldi", count: 0 },
  ],
  food_type: [{ code: "dairy", label: "Lácteos", count: 5 }],
  nutrition: [
    { code: "high_protein", label: "Alto en proteína", count: 3, description: "…" },
    { code: "low_fat", label: "Bajo en grasa", count: 0 },
  ],
};

describe("toggleOption", () => {
  it("adds and removes an option without touching the others", () => {
    let f = toggleOption(emptyFilters(), "supermarket", "lidl");
    f = toggleOption(f, "supermarket", "aldi");
    f = toggleOption(f, "nutrition", "low_fat");
    expect(f).toEqual({ supermarket: ["lidl", "aldi"], food_type: [], nutrition: ["low_fat"] });
    f = toggleOption(f, "supermarket", "lidl");
    expect(f.supermarket).toEqual(["aldi"]);
    expect(activeCount(f)).toBe(2);
    expect(activeCount(f, "nutrition")).toBe(1);
  });
});

describe("hasCriteria", () => {
  it("needs two letters or a filter, otherwise the page shows suggestions", () => {
    expect(hasCriteria("", emptyFilters())).toBe(false);
    expect(hasCriteria("a", emptyFilters())).toBe(false);
    expect(hasCriteria("  po ", emptyFilters())).toBe(true);
    expect(hasCriteria("", toggleOption(emptyFilters(), "food_type", "dairy"))).toBe(true);
  });
});

describe("toSearchQuery", () => {
  it("repeats multi-value filters, trims the text and asks for facets when told", () => {
    const filters = { supermarket: ["lidl", "aldi"], food_type: ["dairy"], nutrition: ["high_protein", "low_fat"] };
    const qs = new URLSearchParams(toSearchQuery({ query: " yogur ", filters, sort: "protein_desc", facets: true, offset: 40 }));
    expect(qs.get("q")).toBe("yogur");
    expect(qs.getAll("supermarket")).toEqual(["lidl", "aldi"]);
    expect(qs.getAll("nutrition")).toEqual(["high_protein", "low_fat"]);
    expect(qs.get("sort")).toBe("protein_desc");
    expect(qs.get("facets")).toBe("true");
    expect(qs.get("offset")).toBe("40");
    expect(qs.get("limit")).toBe("20");
  });

  it("leaves out the defaults and one-letter text", () => {
    const qs = new URLSearchParams(toSearchQuery({ query: "a", filters: emptyFilters(), sort: "relevance" }));
    expect(qs.has("q")).toBe(false);
    expect(qs.has("sort")).toBe(false);
    expect(qs.has("facets")).toBe(false);
    expect(qs.has("offset")).toBe(false);
  });

  it("escapes what the user typed", () => {
    const qs = toSearchQuery({ query: "a&b=c", filters: emptyFilters(), sort: "relevance" });
    expect(qs).toContain("q=a%26b%3Dc");
  });
});

describe("activeChips and visibleOptions", () => {
  it("names the chosen filters with the labels from the server", () => {
    const filters = { supermarket: ["lidl"], food_type: [], nutrition: ["low_fat"] };
    expect(activeChips(filters, facets).map((c) => c.label)).toEqual(["Lidl", "Bajo en grasa"]);
    expect(activeChips(filters, null).map((c) => c.label)).toEqual(["lidl", "low_fat"]);
  });

  it("hides empty options unless chosen, but always lists every nutrition tag", () => {
    expect(visibleOptions("supermarket", facets.supermarket, []).map((o) => o.code)).toEqual(["lidl"]);
    expect(visibleOptions("supermarket", facets.supermarket, ["aldi"]).map((o) => o.code)).toEqual(["lidl", "aldi"]);
    expect(visibleOptions("nutrition", facets.nutrition, []).length).toBe(2);
  });
});

describe("la búsqueda cabe en la barra de direcciones", () => {
  it("no ensucia la URL cuando no hay nada elegido", () => {
    expect(toUrlParams("", emptyFilters(), "relevance")).toBe("");
  });

  it("lleva texto, filtros y orden", () => {
    const filters = { ...emptyFilters(), supermarket: ["mercadona", "lidl"], nutrition: ["high_protein"] };
    const params = new URLSearchParams(toUrlParams(" yogur ", filters, "protein_desc"));
    expect(params.get("q")).toBe("yogur");
    expect(params.get("supermarket")).toBe("mercadona,lidl");
    expect(params.get("nutrition")).toBe("high_protein");
    expect(params.get("sort")).toBe("protein_desc");
  });

  it("lo que sale vuelve a entrar igual: es lo que hace que volver conserve los filtros", () => {
    const filters = { ...emptyFilters(), supermarket: ["mercadona"], food_type: ["fish"] };
    const restored = fromUrlParams(toUrlParams("atún", filters, "kcal_asc"));
    expect(restored).toEqual({ query: "atún", filters, sort: "kcal_asc" });
  });

  it("una URL vacía o manipulada no rompe la pantalla", () => {
    expect(fromUrlParams("")).toEqual({ query: "", filters: emptyFilters(), sort: "relevance" });
    expect(fromUrlParams("sort=inventado&supermarket=").sort).toBe("relevance");
    expect(fromUrlParams("supermarket=,,").filters.supermarket).toEqual([]);
  });
});
