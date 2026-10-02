// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BarChart } from "@/components/charts";
import { MedicalDisclaimer } from "@/components/MedicalDisclaimer";
import { CollapsibleNotice, NoticePrefsProvider } from "@/components/Notices";

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("CollapsibleNotice", () => {
  it("folds down to its title and remembers it in the account", async () => {
    const fetchMock = stubFetch();
    render(
      <NoticePrefsProvider initial={[]}>
        <CollapsibleNotice id="medical-chat" title="No es consejo médico">
          El texto largo del aviso.
        </CollapsibleNotice>
      </NoticePrefsProvider>,
    );
    const toggle = screen.getByRole("button", { name: /No es consejo médico/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("El texto largo del aviso.")).toBeInTheDocument();

    await userEvent.click(toggle);

    // Plegado no desaparece: queda el título a la vista.
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("El texto largo del aviso.")).toBeNull();
    expect(screen.getByText("No es consejo médico")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/profile/ui-prefs",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ collapsed_notices: ["medical-chat"] }),
      }),
    );

    await userEvent.click(toggle);
    expect(screen.getByText("El texto largo del aviso.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/profile/ui-prefs",
      expect.objectContaining({ body: JSON.stringify({ collapsed_notices: [] }) }),
    );
  });

  it("starts folded for a user who left it folded, and only that one", () => {
    stubFetch();
    render(
      <NoticePrefsProvider initial={["medical-chat"]}>
        <CollapsibleNotice id="medical-chat" title="Aviso del chat">
          Cuerpo del chat.
        </CollapsibleNotice>
        <CollapsibleNotice id="medical-plans" title="Aviso de los planes">
          Cuerpo de los planes.
        </CollapsibleNotice>
      </NoticePrefsProvider>,
    );
    expect(screen.queryByText("Cuerpo del chat.")).toBeNull();
    expect(screen.getByText("Aviso del chat")).toBeInTheDocument();
    expect(screen.getByText("Cuerpo de los planes.")).toBeInTheDocument();
  });

  it("still folds without a session, it just is not saved anywhere", async () => {
    const fetchMock = stubFetch();
    render(
      <CollapsibleNotice id="estimate-note" title="Estimación orientativa">
        Cuerpo.
      </CollapsibleNotice>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Estimación orientativa/ }));
    expect(screen.queryByText("Cuerpo.")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("MedicalDisclaimer", () => {
  it("is always shown in full where it cannot be folded (sign-up)", () => {
    render(<MedicalDisclaimer collapsible={false} />);
    expect(screen.getByText(/MyFood no da consejo médico/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("BarChart", () => {
  it("keeps the figure of the longest bar inside the chart", () => {
    // En Perfil la barra más larga es casi siempre la de carbohidratos, y su cifra se
    // pintaba más allá del borde del gráfico: no se veía cuántos había que comer.
    const { container } = render(
      <BarChart
        unit=" g"
        data={[
          { label: "Proteína", value: 150, color: "#00f" },
          { label: "Grasa", value: 70, color: "#ff0" },
          { label: "Carbos", value: 310.5, color: "#0f0" },
        ]}
      />,
    );
    const width = Number(container.querySelector("svg")!.getAttribute("viewBox")!.split(" ")[2]);
    const figures = [...container.querySelectorAll("text")].filter((t) => /\d/.test(t.textContent ?? ""));
    expect(figures.map((t) => t.textContent)).toEqual(["150 g", "70 g", "310.5 g"]);
    for (const figure of figures) {
      // ~6,5 px por carácter a 11 px de letra: la cifra entera tiene que caber.
      const end = Number(figure.getAttribute("x")) + (figure.textContent ?? "").length * 6.5;
      expect(end).toBeLessThanOrEqual(width);
    }
  });
});
