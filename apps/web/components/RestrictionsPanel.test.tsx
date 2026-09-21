// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();
vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
  errorMessage: (e: unknown) => String(e),
}));

import { RestrictionsPanel } from "@/components/RestrictionsPanel";

describe("RestrictionsPanel", () => {
  beforeEach(() => apiFetch.mockReset());

  it("lists the restrictions the API returns as {items: [...]} (regression: it expected a bare array and crashed the profile)", async () => {
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/restrictions") {
        return {
          items: [
            { id: "1", kind: "allergen", allergen_code: "gluten", allergen_name: "Gluten", food_id: null, food_name: null, note: null },
          ],
        };
      }
      return { items: [{ code: "gluten", name_es: "Gluten" }] };
    });
    render(<RestrictionsPanel />);
    expect(await screen.findByRole("button", { name: "Quitar restricción Gluten" })).toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    apiFetch.mockImplementation(async (path: string) => (path === "/api/restrictions" ? { items: [] } : { items: [] }));
    render(<RestrictionsPanel />);
    expect(await screen.findByText(/Todavía no has declarado ninguna restricción/)).toBeInTheDocument();
  });
});
