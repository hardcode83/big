import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen, waitFor } from "@/test/render";
import { ProvenancePanel } from "./provenance-panel";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ status: "authenticated" }),
}));
vi.mock("@/lib/auth/session-store", () => ({
  getSessionTokens: () => ({ accessToken: "ephemeral" }),
}));
vi.mock("@/lib/config/runtime-config-provider", () => ({
  useRuntimeConfig: () => ({ apiBaseUrl: "" }),
}));

afterEach(() => vi.unstubAllGlobals());

function renderPanel() {
  return render(
    <I18nProvider locale="en">
      <ProvenancePanel />
    </I18nProvider>,
  );
}

describe("ProvenancePanel", () => {
  it("requests provenance only when opened and renders complete links", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          app_version: "0.1.0",
          provenance: {
            repository_url: "https://github.com/example/project",
            pull_request_number: 12,
            commit_sha: "a".repeat(40),
            actions_run_id: 34,
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();
    expect(fetchMock).not.toHaveBeenCalled();

    await expect(screen.getByRole("button", { name: "Build provenance" })).toBeInTheDocument();
    screen.getByRole("button", { name: "Build provenance" }).click();
    await waitFor(() => expect(screen.getByRole("link", { name: "Pull request" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Commit" })).toHaveAttribute(
      "href",
      `https://github.com/example/project/commit/${"a".repeat(40)}`,
    );
  });

  it("treats incomplete provenance as unknown and creates no links", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ app_version: "0.1.0", provenance: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    renderPanel();
    screen.getByRole("button", { name: "Build provenance" }).click();
    await waitFor(() => expect(screen.getByText("Unknown provenance.")).toBeInTheDocument());
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
