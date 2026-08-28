import { render, screen, waitFor } from "@/test/render";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { QueryProvider } from "@/lib/query/query-provider";
import { AuthProvider } from "@/lib/auth";
import { useRuntimeConfig } from "@/lib/config/runtime-config-provider";
import WelcomePage from "./page";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  url: "/welcome?role=CLEANER",
  status: "authenticated" as
    | "authenticated"
    | "anonymous"
    | "loading"
    | "refreshing"
    | "expired",
  user: { role: "CLEANER" } as null | { role: string },
}));

// WelcomePage uses `useAuth()` directly from `@/lib/auth`, which throws if the
// context is missing. Stub both the auth provider and the runtime-config
// provider (AuthProvider depends on it for the API base URL) and render the
// page inside QueryProvider so any future change that pulls in
// `useLogoutMutation` from a descendant also has a stable client.
vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return {
    ...actual,
    useAuth: () => ({ status: mocks.status, user: mocks.user }),
  };
});
vi.mock("@/lib/config/runtime-config-provider", () => ({
  useRuntimeConfig: () => ({ apiBaseUrl: "" }),
  RuntimeConfigProvider: ({ children }: { children: React.ReactNode }) => children,
}));
// AuthProvider calls notifySessionExpired at mount; give it a stable no-op.
vi.mock("@/lib/api/authenticated-client", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/authenticated-client")
  >("@/lib/api/authenticated-client");
  return {
    ...actual,
    notifySessionExpired: () => {},
    createAuthenticatedClients: () => ({
      apiClient: { request: vi.fn() },
      refreshTokens: vi.fn(),
    }),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(new URL(mocks.url, "http://test").search),
}));

function renderPage() {
  return render(
    <QueryProvider>
      <I18nProvider locale="es">
        <AuthProvider>
          <WelcomePage />
        </AuthProvider>
      </I18nProvider>
    </QueryProvider>,
  );
}

describe("WelcomePage (R2)", () => {
  beforeEach(() => {
    mocks.replace.mockReset();
    mocks.status = "authenticated";
    mocks.user = { role: "CLEANER" };
    mocks.url = "/welcome?role=CLEANER";
    window.history.replaceState({}, "", "/welcome?role=CLEANER");
  });

  it("renders the CTA when ?role=CLEANER matches user.role=CLEANER", () => {
    renderPage();
    const cta = screen.getByRole("link", { name: /Ir a mis tareas/ });
    expect(cta).toHaveAttribute("href", "/cleaner");
  });

  it("redirects when ?role=TENANT_OWNER mismatches user.role=CLEANER", async () => {
    mocks.url = "/welcome?role=TENANT_OWNER";
    window.history.replaceState({}, "", "/welcome?role=TENANT_OWNER");
    mocks.user = { role: "CLEANER" };

    renderPage();

    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith("/cleaner"),
    );
    expect(
      screen.queryByRole("link", { name: /Ir a mis tareas/ }),
    ).not.toBeInTheDocument();
  });

  it("redirects when ?role is absent (R2 #3)", async () => {
    mocks.url = "/welcome";
    window.history.replaceState({}, "", "/welcome");
    mocks.user = { role: "TECHNICIAN" };

    renderPage();

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/tech"));
  });

  it("renders the busy state while auth is loading", () => {
    mocks.status = "loading";

    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Comprobando sesión…",
    );
  });
});