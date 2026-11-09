import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SystemStatus } from "@/api/client";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { ProviderSwitch } from "./ProviderSwitch";

function status(over: Partial<SystemStatus> = {}): SystemStatus {
  return {
    app_env: "development",
    configured_provider: "mock",
    provider: "mock",
    provider_choice: null,
    can_choose_provider: true,
    cloud_configured: false,
    slot_live: false,
    next_slot: null,
    next_slot_start: null,
    offline_demo_mode: false,
    reason: null,
    upload_max_mb: 50,
    quick_mode_forced: false,
    background_paused: false,
    ...over,
  };
}

/** Serves the status; PUT /api/system/provider switches it like the backend would. */
function serve(initial: SystemStatus) {
  let current = initial;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    if (path === "/api/system/status") return new Response(JSON.stringify(current));
    if (path === "/api/system/provider" && init?.method === "PUT") {
      const { provider } = JSON.parse(String(init.body)) as { provider: string };
      const paused = provider === "cloud" && !current.cloud_configured;
      current = {
        ...current,
        provider_choice: provider,
        provider,
        offline_demo_mode: paused,
        reason: paused ? "cloud_not_configured" : null,
      };
      return new Response(JSON.stringify({ provider_choice: provider, refresh_job_id: "j1" }));
    }
    if (path === "/api/jobs/j1")
      return new Response(
        JSON.stringify({ id: "j1", status: "running", stage: null, stages: [], result: null }),
      );
    return new Response('{"detail":"errors.unexpected"}', { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function show(lang: Language = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <ProviderSwitch />
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ProviderSwitch", () => {
  it("offers the competition cloud models and my local Ollama models", async () => {
    serve(status());
    show();
    const group = await screen.findByRole("radiogroup", { name: "AI models" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Competition cloud models" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("radio", { name: "My local models (Ollama)" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByText(/Mock/)).toBeInTheDocument(); // what runs until a choice is made
  });

  it("switches to local models and shows the material being updated", async () => {
    const fetchMock = serve(status());
    show();
    await userEvent.click(await screen.findByRole("radio", { name: "My local models (Ollama)" }));
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "My local models (Ollama)" })).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ provider: "local" });
    expect(
      await screen.findByText("Updating the course material with these models…"),
    ).toBeInTheDocument();
  });

  it("says why cloud is paused when the key is missing", async () => {
    serve(status());
    show();
    await userEvent.click(await screen.findByRole("radio", { name: "Competition cloud models" }));
    expect(await screen.findByText("Cloud key not set in .env: AI is paused.")).toBeInTheDocument();
  });

  it("is hidden in production", async () => {
    const fetchMock = serve(status({ app_env: "production", can_choose_provider: false }));
    show();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });

  it("works in Arabic", async () => {
    serve(status());
    show("ar");
    expect(await screen.findByRole("radio", { name: "نماذجي المحلية (Ollama)" })).toBeVisible();
  });
});
