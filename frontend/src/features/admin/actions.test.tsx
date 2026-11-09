import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeleteAction, UserActions } from "./actions";
import type { UserDetail } from "./types";

const u: UserDetail = {
  id: "u1",
  nickname: "ana_admin",
  ui_language: "en",
  created_at: "2026-11-01T10:00:00Z",
  session_epoch: 0,
  dev_user: false,
  wallet: { free: 20, earned: 0, purchased: 0, coins: 20, pass_until: null, pass_active: false },
  points: 0,
  streak: 0,
  worlds: [],
  levels: [],
  counts: {},
  coin_ledger: [],
  points_ledger: [],
  jobs: [],
};

function serve() {
  const calls: { path: string; method: string; body?: unknown; headers: Record<string, string> }[] =
    [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url).pathname;
      const method = init?.method ?? "GET";
      calls.push({
        path,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        headers: (init?.headers ?? {}) as Record<string, string>,
      });
      if (path.endsWith("/dry-run"))
        return new Response(
          JSON.stringify({ confirm_text: "limits.pdf", counts: { documents: 1 }, blocked_by: [] }),
        );
      return new Response("{}");
    }),
  );
  return calls;
}

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Admin actions", () => {
  it("grants coins only with a reason, as a ledger request with the CSRF header", async () => {
    const calls = serve();
    wrap(<UserActions u={u} />);
    await userEvent.click(screen.getByText("Grant or remove coins"));
    const grant = screen.getByRole("button", { name: "Grant 5 coins" });
    expect(grant).toBeDisabled();
    const reasons = screen.getAllByLabelText("Reason (required)");
    await userEvent.type(reasons[0]!, "demo top-up");
    await userEvent.click(grant);
    const post = calls.find((c) => c.path === "/api/admin/users/u1/coins");
    expect(post?.body).toEqual({ bucket: "earned", delta: 5, reason: "demo top-up" });
    expect(post?.headers["X-Admin-Action"]).toBe("1");
  });

  it("deletes only after a dry run and the exact name", async () => {
    const calls = serve();
    wrap(<DeleteAction kind="document" id="d1" label="limits.pdf" />);
    await userEvent.click(screen.getByText("Delete limits.pdf…"));
    await userEvent.click(screen.getByRole("button", { name: "Dry run" }));
    expect(await screen.findByText("documents:")).toBeInTheDocument();
    const del = screen.getByRole("button", { name: "Delete limits.pdf" });
    await userEvent.type(screen.getByLabelText('Type "limits.pdf" to confirm'), "limits");
    await userEvent.type(screen.getByLabelText("Reason (required)"), "duplicate upload");
    expect(del).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Type "limits.pdf" to confirm'), ".pdf");
    await userEvent.click(del);
    const d = calls.find((c) => c.method === "DELETE");
    expect(d?.path).toBe("/api/admin/delete/document/d1");
    expect(d?.body).toEqual({ confirm: "limits.pdf", reason: "duplicate upload" });
  });
});
