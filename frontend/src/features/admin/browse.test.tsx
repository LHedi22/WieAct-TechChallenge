import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminApp from "./AdminApp";

const user = {
  id: "u1",
  nickname: "ana_admin",
  created_at: "2026-11-01T10:00:00Z",
  ui_language: "ar",
  worlds: 1,
  wallet: { free: 17, earned: 7, purchased: 0, coins: 24, pass_until: null, pass_active: false },
  points: 30,
  streak: 2,
  last_seen: null,
  dev_user: false,
};

function serve() {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const u = new URL(url);
      seen.push(`${u.pathname}${u.search}`);
      if (u.pathname === "/api/admin/me")
        return new Response(JSON.stringify({ actor: "Hedi", via: "cookie", expires_at: null }));
      if (u.pathname === "/api/admin/users")
        return new Response(
          JSON.stringify({
            items: [user],
            total: 120,
            page: Number(u.searchParams.get("page")),
            page_size: 50,
          }),
        );
      return new Response('{"detail":"Not Found"}', { status: 404 });
    }),
  );
  return seen;
}

afterEach(() => vi.unstubAllGlobals());

describe("Admin read pages", () => {
  it("lists users with ledger wallets, searches server-side and pages by 50", async () => {
    const seen = serve();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/users"]}>
          <Routes>
            <Route path="/admin/*" element={<AdminApp />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
    expect((await screen.findAllByText("24 (17/7/0)")).length).toBeGreaterThan(0);
    expect(screen.getByText("Page 1 of 3 · 120 total")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Nickname"), "ana");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Pages" })).getByRole("button", {
        name: "Next",
      }),
    );
    expect(seen).toContain("/api/admin/users?q=ana&page=1");
    expect(seen).toContain("/api/admin/users?q=ana&page=2");
  });
});
