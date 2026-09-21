// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FacetSheet } from "@/components/foods/FacetSheet";
import { FoodRow } from "@/components/foods/FoodCard";
import { MacroPreview, PortionPicker } from "@/components/foods/PortionPicker";
import type { FacetOption, FoodSearchItem } from "@/lib/types";

const row: FoodSearchItem = {
  id: "abc",
  name_es: "Yogur natural 0%",
  brand: "Hacendado",
  kcal_100g: 36.4,
  protein_100g: 4.3,
  fat_100g: 0.1,
  carbs_100g: 4.5,
  image_url: null,
  source: "off",
  supermarket: "Mercadona",
};

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

describe("PortionPicker", () => {
  const huevo = { key: "unit_egg", label: "huevo", grams: 60 };
  const gramos = { key: "g", label: "gramos", grams: 1 };

  function picker(over: Partial<React.ComponentProps<typeof PortionPicker>> = {}) {
    const props = {
      portions: [huevo, gramos],
      portion: huevo,
      quantity: 1,
      onChange: vi.fn(),
      ...over,
    };
    render(<PortionPicker {...props} />);
    return props;
  }

  it("ofrece cada medida con lo que pesa, para no tener que adivinarlo", () => {
    picker();
    expect(screen.getByRole("option", { name: "huevo (60 g)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "gramos" })).toBeInTheDocument();
  });

  it("los botones de más y menos mueven la cantidad", async () => {
    const props = picker({ quantity: 2 });
    await userEvent.click(screen.getByRole("button", { name: "Añadir" }));
    expect(props.onChange).toHaveBeenCalledWith({ portion: huevo, quantity: 2.5 });
  });

  it("no deja bajar de la cantidad mínima", () => {
    picker({ quantity: 0.5 });
    expect(screen.getByRole("button", { name: "Quitar" })).toBeDisabled();
  });

  it("al cambiar de medida conserva lo que pesa, no el número", async () => {
    // «2 huevos» son 120 g: pasar a gramos debe dar 120, no 2.
    const props = picker({ quantity: 2 });
    await userEvent.selectOptions(screen.getByLabelText("Medida"), "g");
    expect(props.onChange).toHaveBeenCalledWith({ portion: gramos, quantity: 120 });
  });
});

describe("MacroPreview", () => {
  const pollo = { kcal_100g: 165, protein_100g: 31, carbs_100g: 0, fat_100g: 3.6 };

  it("enseña lo que va a sumar al día antes de confirmar", () => {
    render(
      <MacroPreview
        per100g={pollo}
        grams={200}
        quantity={200}
        portion={{ key: "g", label: "gramos", grams: 1 }}
      />,
    );
    expect(screen.getByText("330 kcal")).toBeInTheDocument();
    expect(screen.getByText("62 g")).toBeInTheDocument();
    expect(screen.getByText("200 g")).toBeInTheDocument();
  });

  it("con una medida casera dice también a cuántos gramos equivale", () => {
    render(
      <MacroPreview
        per100g={pollo}
        grams={120}
        quantity={2}
        portion={{ key: "unit_egg", label: "huevo", grams: 60 }}
      />,
    );
    expect(screen.getByText("2 huevos (120 g)")).toBeInTheDocument();
  });
});

describe("FoodRow: añadir sin salir de la lista", () => {
  it("el botón de añadir no navega a la ficha", async () => {
    const onAdd = vi.fn();
    render(<FoodRow item={row} onAdd={onAdd} />);
    await userEvent.click(screen.getByRole("button", { name: /Añadir .* al diario/ }));
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it("sin manejador no aparece el botón: la tarjeta sigue siendo solo un enlace", () => {
    render(<FoodRow item={row} />);
    expect(screen.queryByRole("button", { name: /al diario/ })).not.toBeInTheDocument();
  });
});
