// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FacetSheet } from "@/components/foods/FacetSheet";
import { FoodRow } from "@/components/foods/FoodCard";
import type { FacetOption, FoodSearchItem } from "@/lib/types";

const supermarkets: FacetOption[] = [
  { code: "mercadona", label: "Mercadona", count: 45 },
  { code: "lidl", label: "Lidl", count: 12 },
  { code: "aldi", label: "Aldi", count: 0 },
];

function sheet(over: Partial<React.ComponentProps<typeof FacetSheet>> = {}) {
  const props = {
    facetKey: "supermarket" as const,
    options: supermarkets,
    selected: [] as string[],
    total: 57,
    loading: false,
    onToggle: vi.fn(),
    onClear: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  render(<FacetSheet {...props} />);
  return props;
}

describe("FacetSheet", () => {
  it("lists the options that leave something, with their counts, and toggles them", async () => {
    const props = sheet();
    expect(screen.getByRole("dialog", { name: "Supermercado" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Mercadona/ })).not.toBeChecked();
    expect(screen.getByText("45")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Aldi/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /Lidl/ }));
    expect(props.onToggle).toHaveBeenCalledWith("lidl");
  });

  it("keeps a chosen option visible even when it now leaves nothing, so it can be removed", () => {
    sheet({ selected: ["aldi"] });
    expect(screen.getByRole("checkbox", { name: /Aldi/ })).toBeChecked();
  });

  it("says how many foods the choice leaves, or just «Listo» while nothing is chosen", () => {
    sheet({ selected: ["lidl"], total: 12 });
    expect(screen.getByRole("button", { name: "Ver 12 alimentos" })).toBeInTheDocument();
  });

  it("uses «Listo» when there is nothing to search yet", () => {
    sheet({ total: null });
    expect(screen.getByRole("button", { name: "Listo" })).toBeInTheDocument();
  });

  it("clears only when something is chosen", () => {
    sheet({ selected: [] });
    expect(screen.getByRole("button", { name: "Quitar" })).toBeDisabled();
  });

  it("renders nothing when no filter is open", () => {
    sheet({ facetKey: null });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("FoodRow", () => {
  const item: FoodSearchItem = {
    id: "abc",
    name_es: "Yogur natural 0%",
    brand: "Hacendado, MERCADONA",
    kcal_100g: 36.4,
    protein_100g: 4.3,
    fat_100g: 0.1,
    carbs_100g: 4.5,
    image_url: null,
    source: "off",
    supermarket: "Mercadona",
    food_type: "Lácteos",
    nutriscore_grade: "a",
  };

  it("links to the food and shows where it is sold, its brand and its macros per 100 g", () => {
    render(<FoodRow item={item} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/foods/abc");
    expect(screen.getByText("Mercadona")).toBeInTheDocument();
    expect(screen.getByText("Hacendado")).toBeInTheDocument();
    expect(screen.getByText("36 kcal")).toBeInTheDocument();
    expect(screen.getByText(/P 4\.3 g/)).toBeInTheDocument();
  });

  it("copes with a generic food without brand or store", () => {
    render(<FoodRow item={{ ...item, brand: null, supermarket: null, fat_100g: null }} />);
    expect(screen.getByText("Lácteos")).toBeInTheDocument();
    expect(screen.getByText(/G —/)).toBeInTheDocument();
  });
});
