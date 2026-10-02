// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DiaryProposalCard } from "@/components/chat/DiaryProposalCard";
import type { ChatDiaryPayload } from "@/lib/types";

const today = new Date();
const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(
  today.getDate(),
).padStart(2, "0")}`;

const payload: ChatDiaryPayload = {
  date: iso,
  meal_type: "morning_snack",
  request: "una marinera, una caña y un yogur",
  has_estimates: true,
  totals: { kcal: 470, protein_g: 14, fat_g: 11, carbs_g: 52 },
  items: [
    {
      name: "Marinera",
      grams: 130,
      kcal: 260,
      protein_g: 8,
      fat_g: 9,
      carbs_g: 38,
      food_id: null,
      estimated: true,
      quantity: 1,
      meal_type: "morning_snack",
      components: [
        { name: "rosquilla", grams: 60, kcal: 160 },
        { name: "ensaladilla rusa", grams: 60, kcal: 90 },
        { name: "anchoa", grams: 10, kcal: 10 },
      ],
    },
    {
      name: "Caña de cerveza",
      grams: 200,
      kcal: 90,
      protein_g: 1,
      fat_g: 0,
      carbs_g: 7,
      food_id: "11111111-1111-1111-1111-111111111111",
      estimated: true,
      from_catalog: true,
      quantity: 1,
      meal_type: "morning_snack",
    },
    {
      name: "Yogur natural",
      grams: 125,
      kcal: 120,
      protein_g: 5,
      fat_g: 2,
      carbs_g: 7,
      food_id: "22222222-2222-2222-2222-222222222222",
      estimated: false,
      meal_type: "morning_snack",
    },
  ],
};

describe("DiaryProposalCard", () => {
  it("shows every estimate as approximate, and catalog data as it is", () => {
    render(<DiaryProposalCard payload={payload} deciding={false} onDecide={() => {}} />);

    // Lo estimado lleva «aprox.»; el dato del catálogo, no.
    expect(screen.getByText("aprox. 260 kcal")).toBeInTheDocument();
    expect(screen.getByText("aprox. 90 kcal")).toBeInTheDocument();
    expect(screen.getByText("120 kcal")).toBeInTheDocument();
    // Y el total, que mezcla estimaciones, también.
    expect(screen.getByText("aprox. 470 kcal")).toBeInTheDocument();
    expect(screen.getByText(/estimación orientativa, no una medición/)).toBeInTheDocument();
    // Sin nada confirmado por el catálogo no se habla de él.
    expect(screen.queryByText(/toma sus valores por 100 g del catálogo/)).toBeNull();
  });

  it("shows what a dish is made of", () => {
    render(<DiaryProposalCard payload={payload} deciding={false} onDecide={() => {}} />);

    expect(screen.getByText(/rosquilla/)).toBeInTheDocument();
    expect(screen.getByText(/ensaladilla rusa/)).toBeInTheDocument();
    expect(screen.getByText(/anchoa/)).toBeInTheDocument();
  });

  it("shows the grams of each part and which ones take their values from the catalog", () => {
    const refined: ChatDiaryPayload = {
      ...payload,
      items: [
        {
          ...payload.items[0],
          name: "Bocadillo de jamón",
          components: [
            { name: "pan", grams: 100, kcal: 262, catalog: "Pan blanco de barra" },
            { name: "jamón serrano", grams: 40, kcal: 94, catalog: "Jamón curado Serrano" },
            { name: "alioli casero", grams: 5, kcal: 35 },
          ],
        },
        { ...payload.items[2], name: "Manzana", estimated: true, food_id: null, catalog: "Manzana Gala" },
      ],
    };
    render(<DiaryProposalCard payload={refined} deciding={false} onDecide={() => {}} />);

    // «Bocadillo de jamón (pan 100 g, jamón 40 g…)»: cada parte con sus gramos.
    expect(screen.getByText("100 g")).toBeInTheDocument();
    expect(screen.getByText("40 g")).toBeInTheDocument();
    expect(screen.getByText("5 g")).toBeInTheDocument();
    // Dos partes confirmadas por el catálogo, una estimada; y la manzana, confirmada entera.
    expect(screen.getAllByRole("img", { name: "Valores del catálogo" })).toHaveLength(2);
    expect(screen.getByText("valores del catálogo")).toBeInTheDocument();
    // Sigue siendo una estimación: los gramos son a ojo.
    expect(screen.getByText(/las cantidades son a ojo/)).toBeInTheDocument();
  });

  it("offers saving only the dishes that are not in the catalog yet", async () => {
    const onDecide = vi.fn();
    render(<DiaryProposalCard payload={payload} deciding={false} onDecide={onDecide} />);

    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(1);
    expect(screen.getByLabelText("Guardar «Marinera» en el catálogo")).toBe(boxes[0]);
    expect(screen.getByText("guardado")).toBeInTheDocument();

    await userEvent.click(boxes[0]);
    await userEvent.click(screen.getByRole("button", { name: /Sí, apúntalo y guárdalo/ }));
    expect(onDecide).toHaveBeenCalledWith("approve", [0]);
  });

  it("approves without saving anything by default, and rejects with nothing to save", async () => {
    const onDecide = vi.fn();
    render(<DiaryProposalCard payload={payload} deciding={false} onDecide={onDecide} />);

    await userEvent.click(screen.getByRole("button", { name: /Sí, apúntalo/ }));
    expect(onDecide).toHaveBeenLastCalledWith("approve", []);
    await userEvent.click(screen.getByRole("button", { name: "No" }));
    expect(onDecide).toHaveBeenLastCalledWith("reject", []);
  });

  it("says which meal each dish goes to when the message spans several", () => {
    const split: ChatDiaryPayload = {
      ...payload,
      items: [payload.items[0], { ...payload.items[2], meal_type: "dinner" }],
    };
    render(<DiaryProposalCard payload={split} deciding={false} onDecide={() => {}} />);

    expect(screen.getByText(/cada plato en su comida/)).toBeInTheDocument();
    expect(screen.getByText("Media mañana")).toBeInTheDocument();
    expect(screen.getByText("Cena")).toBeInTheDocument();
  });
});
