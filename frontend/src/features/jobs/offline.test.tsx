import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SystemStatus } from "@/api/client";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { GeneratePanel } from "@/features/studio/GeneratePanel";
import { OfflineBanner } from "./ProviderBadge";

function status(offline: boolean): SystemStatus {
  return {
    app_env: "production",
    configured_provider: "cloud",
    provider: "cloud",
    slot_live: !offline,
    next_slot: "Mon 02/11 00:00-12:00",
    next_slot_start: "2026-11-02T00:00:00+01:00",
    offline_demo_mode: offline,
    reason: offline ? "outside_slot" : null,
    upload_max_mb: 50,
  };
}

function serve(offline: boolean) {
  const routes: Record<string, unknown> = {
    "/api/system/status": status(offline),
    "/api/wallet": { coins: 20 },
    "/api/worlds/w1/pool": { balance: 0, max_contribution: 50, recent: [] },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const out = routes[new URL(url).pathname];
      return out === undefined
        ? new Response('{"detail":"errors.unexpected"}', { status: 404 })
        : new Response(JSON.stringify(out), { status: 200 });
    }),
  );
}

function show(ui: ReactElement, lang: Language = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

const panel = (
  <GeneratePanel
    cost={15}
    poolBalance={0}
    title="Study pack"
    body="Notes, cards and a map"
    worldId="w1"
    busy={false}
    onGenerate={() => {}}
  />
);

afterEach(() => vi.unstubAllGlobals());

describe("offline demo mode", () => {
  it("shows the banner with when AI actions resume", async () => {
    serve(true);
    show(<OfflineBanner />);
    expect(await screen.findByText(/Offline demo mode/)).toHaveTextContent(/resume/);
  });

  it("shows no banner while the slot is live", async () => {
    serve(false);
    const { container } = show(<OfflineBanner />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });

  it("disables generating new material, in Arabic too", async () => {
    serve(true);
    show(panel, "ar");
    expect(await screen.findByText(/وضع العرض دون اتصال/)).toBeInTheDocument();
    expect(within(screen.getByTestId("generate-panel")).getByRole("button")).toBeDisabled();
  });

  it("keeps generating enabled while the slot is live", async () => {
    serve(false);
    show(panel);
    await screen.findByText("Study pack");
    await new Promise((r) => setTimeout(r, 20));
    expect(within(screen.getByTestId("generate-panel")).getByRole("button")).toBeEnabled();
  });
});
