import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "@/features/auth";
import { AuthProvider, useAuth } from "@/lib/auth";
import { clearSessionTokens, getSessionTokens } from "@/lib/auth/session-store";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => router,
}));

function LoginControl() {
  const { login } = useAuth();
  return (
    <button onClick={() => void login("user@example.com", "secret")}>login</button>
  );
}

function ProtectedSurface() {
  const { logout } = useAuth();
  return (
    <AuthGuard>
      <span>protected content</span>
      <button onClick={() => void logout()}>logout</button>
    </AuthGuard>
  );
}

describe("authenticated surface integration", () => {
  afterEach(() => {
    clearSessionTokens();
    router.replace.mockReset();
    vi.unstubAllGlobals();
  });

  it("logs out a protected surface and redirects once to login", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(new Response(JSON.stringify({
          access_token: "access",
          refresh_token: "refresh",
          token_type: "bearer",
          expires_in: 900,
        }), { status: 200 }));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(new Response(JSON.stringify({
          id: "user-1",
          email: "user@example.com",
          name: "User",
          preferred_language: "es",
          role: "TENANT_OWNER",
          tenant_id: "tenant-1",
        }), { status: 200 }));
      }
      if (url.endsWith("/auth/logout")) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    render(
      <RuntimeConfigProvider
        config={{
          apiBaseUrl: "",
          appEnv: "test",
          defaultLocale: "es",
          featureFlags: {},
          appVersion: "",
          buildCommitShort: "",
          appUrl: "",
        }}
      >
        <I18nProvider locale="es">
          <AuthProvider>
            <LoginControl />
            <ProtectedSurface />
          </AuthProvider>
        </I18nProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByText("protected content")).toBeInTheDocument();
    router.replace.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith(
      "/login?returnTo=%2Fdashboard",
    ));
    expect(router.replace).toHaveBeenCalledOnce();
    expect(getSessionTokens()).toBeNull();
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });
});
