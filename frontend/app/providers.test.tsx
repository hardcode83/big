import { describe, expect, it } from "vitest";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import { render, screen, waitFor } from "@/test/render";
import { AppProviders } from "@/app/providers";
import { useRuntimeConfig } from "@/lib/config/runtime-config-provider";
import { useAuth } from "@/lib/auth";

function Probe() {
  const { appEnv } = useRuntimeConfig();
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const { status } = useAuth();
  return (
    <div>
      <span data-testid="env">{appEnv}</span>
      <span data-testid="app">{t("appName")}</span>
      <span data-testid="query">{queryClient ? "query-ready" : "no-query"}</span>
      <span data-testid="auth">{status}</span>
    </div>
  );
}

describe("AppProviders (D10)", () => {
  it("composes config, i18n and query and renders children without a backend", async () => {
    render(
      <AppProviders
        config={{
          apiBaseUrl: "",
          appEnv: "test",
          defaultLocale: "es",
          featureFlags: {},
          appVersion: "",
          buildCommitShort: "",
          appUrl: "",
        }}
        locale="es"
      >
        <Probe />
      </AppProviders>,
    );

    expect(screen.getByTestId("env")).toHaveTextContent("test");
    expect(screen.getByTestId("app")).toHaveTextContent("AutoHostAI");
    expect(screen.getByTestId("query")).toHaveTextContent("query-ready");
    // A runtime with no tokens in memory opens on `loading` while the silent
    // mount-refresh is in flight (R5.1) — the composed tree is what fires it.
    expect(screen.getByTestId("auth")).toHaveTextContent("loading");
    // "without a backend": the refresh cannot complete here, and R5.3 wants
    // that to land on `anonymous` rather than on any error state.
    await waitFor(() =>
      expect(screen.getByTestId("auth")).toHaveTextContent("anonymous"),
    );
  });
});
