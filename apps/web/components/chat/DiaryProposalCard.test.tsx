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
  });

  it("shows what a dish is made of", () => {
    render(<DiaryProposalCard payload={payload} deciding={false} onDecide={() => {}} />);

    expect(screen.getByText(/rosquilla/)).toBeInTheDocument();
    expect(screen.getByText(/ensaladilla rusa/)).toBeInTheDocument();
    expect(screen.getByText(/anchoa/)).toBeInTheDocument();
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
