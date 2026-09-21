// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BottomSheet } from "@/components/ui/BottomSheet";
import { BudgetRing } from "@/components/ui/BudgetRing";
import { MacroBar } from "@/components/ui/MacroBar";
import { NumberStepper } from "@/components/ui/NumberStepper";
import { Ring } from "@/components/ui/Ring";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { ScoreBadges } from "@/components/ScoreBadges";

describe("Ring", () => {
  it("describes the value against its target in text, not only by color", () => {
    render(<Ring value={1234.6} target={2000} color="#16a34a" label="Energía" unit="kcal" />);
    expect(screen.getByRole("group", { name: "Energía: 1235 de 2000 kcal" })).toBeInTheDocument();
    expect(screen.getByText("Energía")).toBeInTheDocument();
  });

  it("works without a target", () => {
    render(<Ring value={40} target={null} color="#000" label="Agua" unit="ml" />);
    expect(screen.getByRole("group", { name: "Agua: 40 ml" })).toBeInTheDocument();
  });

  it("never draws more than a full ring when the target is exceeded", () => {
    const { container } = render(<Ring value={500} target={100} color="#000" label="x" unit="g" />);
    const arc = container.querySelectorAll("circle")[1];
    expect(Number(arc.getAttribute("stroke-dashoffset"))).toBeCloseTo(0);
  });
});

describe("MacroBar", () => {
  const slices = [
    { key: "p", label: "Proteína", grams: 50, color: "red" },
    { key: "f", label: "Grasa", grams: 30, color: "orange" },
    { key: "c", label: "Carbohidratos", grams: 20, color: "blue" },
  ];

  it("labels every slice with its name and grams", () => {
    render(<MacroBar slices={slices} />);
    expect(screen.getByText("Proteína: 50 g")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName("Proteína 50 %, Grasa 30 %, Carbohidratos 20 %");
  });

  it("says so when there is nothing to split", () => {
    render(<MacroBar slices={slices.map((s) => ({ ...s, grams: 0 }))} />);
    expect(screen.getByText(/Todavía no hay macros/)).toBeInTheDocument();
  });
});

describe("states", () => {
  it("Skeleton announces loading to assistive tech", () => {
    render(<Skeleton lines={2} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Cargando…")).toBeInTheDocument();
  });

  it("EmptyState suggests an action", async () => {
    const onAction = vi.fn();
    render(<EmptyState message="Nada todavía" actionLabel="Añadir" onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: "Añadir" }));
    expect(onAction).toHaveBeenCalledOnce();
  });

  it("EmptyState can link somewhere instead", () => {
    render(<EmptyState message="Nada" actionLabel="Ir" actionHref="/scan" />);
    expect(screen.getByRole("link", { name: "Ir" })).toHaveAttribute("href", "/scan");
  });

  it("ErrorState is an alert with a retry button", async () => {
    const retry = vi.fn();
    render(<ErrorState message="No se pudo cargar" onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar");
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("ErrorState without a retry handler shows no button", () => {
    render(<ErrorState message="Error" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("NumberStepper", () => {
  it("steps by its step and stays inside its bounds", async () => {
    const onChange = vi.fn();
    render(<NumberStepper label="Cantidad" value={100} onChange={onChange} min={0} max={110} step={5} />);
    await userEvent.click(screen.getByRole("button", { name: "Añadir 5 g" }));
    expect(onChange).toHaveBeenLastCalledWith(105);
    await userEvent.click(screen.getByRole("button", { name: "Quitar 5 g" }));
    expect(onChange).toHaveBeenLastCalledWith(95);
  });

  it("disables the buttons at the limits", () => {
    const { rerender } = render(<NumberStepper label="c" value={0} onChange={() => {}} min={0} max={10} />);
    expect(screen.getByRole("button", { name: /Quitar/ })).toBeDisabled();
    rerender(<NumberStepper label="c" value={10} onChange={() => {}} min={0} max={10} />);
    expect(screen.getByRole("button", { name: /Añadir/ })).toBeDisabled();
  });

  it("clamps what is typed", async () => {
    const onChange = vi.fn();
    render(<NumberStepper label="Cantidad" value={5} onChange={onChange} min={0} max={50} />);
    const input = screen.getByRole("spinbutton");
    await userEvent.clear(input);
    await userEvent.type(input, "999");
    expect(onChange).toHaveBeenLastCalledWith(50);
  });
});

describe("BottomSheet", () => {
  it("renders nothing while closed", () => {
    render(
      <BottomSheet open={false} onClose={() => {}} title="Añadir">
        contenido
      </BottomSheet>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is a labelled modal dialog that closes with Escape and with the close button", async () => {
    const onClose = vi.fn();
    render(
      <BottomSheet open onClose={onClose} title="Añadir">
        <button type="button">Escanear</button>
      </BottomSheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Añadir" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps keyboard focus inside while open", async () => {
    render(
      <BottomSheet open onClose={() => {}} title="Añadir">
        <button type="button">Uno</button>
      </BottomSheet>,
    );
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });

  it("gives the focus back to what opened it", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const { rerender } = render(
      <BottomSheet open onClose={() => {}} title="t">
        x
      </BottomSheet>,
    );
    rerender(
      <BottomSheet open={false} onClose={() => {}} title="t">
        x
      </BottomSheet>,
    );
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});

describe("ScoreBadges", () => {
  it("shows only the scores it has and never invents one", () => {
    const { container, rerender } = render(<ScoreBadges nutriscore={null} nova={null} ecoscore={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ScoreBadges nutriscore="b" nova={null} ecoscore={null} />);
    expect(screen.getByText("B")).toBeInTheDocument();
    expect(screen.queryByText("NOVA")).toBeNull();
  });

  it("ignores values outside the official scales", () => {
    const { container } = render(<ScoreBadges nutriscore="z" nova={9} ecoscore="q" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("BudgetRing", () => {
  it("shows what is left and says it in text", () => {
    render(<BudgetRing consumed={1420.4} target={2100} />);
    expect(screen.getByRole("group", { name: "Calorías: 1420 de 2100 kcal. Quedan 680 kcal" })).toBeInTheDocument();
    expect(screen.getByText("680")).toBeInTheDocument();
    expect(screen.getByText("restantes")).toBeInTheDocument();
  });

  it("reports going over without alarm colours", () => {
    const { container } = render(<BudgetRing consumed={2350} target={2100} />);
    expect(screen.getByText("+250")).toBeInTheDocument();
    expect(screen.getByText("sobre el objetivo")).toBeInTheDocument();
    const arc = container.querySelectorAll("circle")[1];
    expect(arc.getAttribute("stroke")).toBe("var(--color-primary)");
    expect(Number(arc.getAttribute("stroke-dashoffset"))).toBeCloseTo(0);
  });

  it("falls back to what was eaten when there is no target", () => {
    render(<BudgetRing consumed={512} target={null} />);
    expect(screen.getByRole("group", { name: "Calorías: 512 kcal" })).toBeInTheDocument();
    expect(screen.getByText("kcal")).toBeInTheDocument();
  });
});
