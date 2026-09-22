// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AdminDashboard } from "@/components/admin/AdminDashboard";
import type { AdminUser } from "@/lib/types";

const user: AdminUser = {
  id: "u1",
  display_name: "Jorge",
  email: "jorge@example.com",
  role: "user",
  is_active: true,
  ai_enabled: false,
  created_at: "2026-09-01T10:00:00Z",
  last_seen_at: "2026-09-20T10:00:00Z",
  invited_with: "ABCDE-FGHIJ",
  logging_days: 12,
  last_log_date: "2026-09-20",
  ai_used_today: 3,
  ai_used_30d: 40,
};

const overview = {
  users_total: 2, users_active: 2, users_with_ai: 1, users_logging_last_7d: 1,
  invites_usable: 0, invite_only: true, food_entries_today: 4, food_entries_7d: 20,
  new_users_30d: 1, top_foods_7d: [{ name: "Yogur natural", uses: 9 }],
  ai_used_today: 30, ai_instance_limit: 30, ai_sessions_30d: 50, ai_failed_7d: 2,
  foods_total: 21807, database_size: "1200 MB", last_food_ingested_at: "2026-09-18T00:00:00Z",
};

function mockApi(patchSpy = vi.fn()) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url);
    if (init?.method === "PATCH") {
      patchSpy(path, JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ ...user, ai_enabled: true }), { status: 200 });
    }
    const body =
      path.includes("/overview") ? overview
      : path.includes("/users") ? [user]
      : path.includes("/invites") ? []
      : path.includes("/activity") ? []
      : { invite_only: true, ai_enabled_by_default: false };
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  return patchSpy;
}

describe("AdminDashboard", () => {
  it("enseña quién tiene cuenta y cuánta IA gasta, sin enseñar lo que ha comido", async () => {
    mockApi();
    render(<AdminDashboard />);
    expect(await screen.findByText("Jorge")).toBeInTheDocument();
    expect(screen.getByText("jorge@example.com")).toBeInTheDocument();
    expect(screen.getByText(/12 días registrando/)).toBeInTheDocument();
    expect(screen.getByText(/invitación ABCDE-FGHIJ/)).toBeInTheDocument();
  });

  it("el interruptor de IA refleja el estado y manda el cambio", async () => {
    const patch = mockApi();
    render(<AdminDashboard />);
    const toggle = await screen.findByRole("switch", { name: "Permitir la IA a Jorge" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    expect(patch).toHaveBeenCalledWith("/api/admin/users/u1", { ai_enabled: true });
  });

  it("avisa cuando la cuota de la casa está agotada", async () => {
    mockApi();
    render(<AdminDashboard />);
    expect(await screen.findByText(/30 peticiones hoy en la casa/)).toBeInTheDocument();
  });

  it("avisa cuando el registro es por invitación y no quedan códigos", async () => {
    mockApi();
    render(<AdminDashboard />);
    expect(await screen.findByText("Registro por invitación")).toBeInTheDocument();
    expect(screen.getByText("Códigos sin usar")).toBeInTheDocument();
  });
});
