import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "@/features/auth";
import { useLogoutMutation } from "@/features/auth/hooks/use-logout-mutation";
import { AuthProvider, useAuth } from "@/lib/auth";
import { subscribeToSessionExpired } from "@/lib/api/authenticated-client";
import { subscribeToLogout } from "@/lib/auth/logout-event";
import { clearSessionTokens, getSessionTokens } from "@/lib/auth/session-store";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { makeQueryClient } from "@/lib/query/query-client";
import { fireEvent, render, screen, waitFor } from "@/test/render";

const router = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => router,
}));

const RUNTIME_CONFIG = {
  apiBaseUrl: "",
  appEnv: "test",
  defaultLocale: "es" as const,
  featureFlags: {},
  appVersion: "",
  buildCommitShort: "",
  appUrl: "",
};

/**
 * The login response as the backend now shapes it: the refresh token is gone
 * from the body and travels only as the `httpOnly` `Set-Cookie` the browser
 * keeps out of JavaScript's reach (R1). Nothing in these flows may read it.
 */
const TOKEN_PAIR = {
  access_token: "access",
  token_type: "bearer",
  expires_in: 900,
};

const CURRENT_USER = {
  id: "user-1",
  email: "user@example.com",
  name: "User",
  preferred_language: "es",
  role: "TENANT_OWNER",
  tenant_id: "tenant-1",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function noSessionCookie(): Response {
  return jsonResponse(
    { error: { code: "UNAUTHENTICATED", message: "No refresh cookie" } },
    401,
  );
}

function LoginControl() {
  const { login } = useAuth();
  return (
    <button onClick={() => void login("user@example.com", "secret")}>login</button>
  );
}

function ProtectedSurface() {
  // Mirrors the real wiring (`UserMenu`, D3/R3): the local-only `useAuth().logout()`
  // wrapper was removed, so this exercises the same `useLogoutMutation()` production
  // code path a click in the app actually runs.
  const logoutMutation = useLogoutMutation();
  return (
    <AuthGuard>
      <span>protected content</span>
      <button onClick={() => void logoutMutation.mutateAsync()}>logout</button>
    </AuthGuard>
  );
}

function renderSession(children: ReactNode, queryClient: QueryClient = makeQueryClient()) {
  const tree = (
    <RuntimeConfigProvider config={RUNTIME_CONFIG}>
      <I18nProvider locale="es">
        <AuthProvider>{children}</AuthProvider>
      </I18nProvider>
    </RuntimeConfigProvider>
  );
  return render(<QueryClientProvider client={queryClient}>{tree}</QueryClientProvider>);
}

describe("authenticated surface integration", () => {
  afterEach(() => {
    clearSessionTokens();
    router.replace.mockReset();
    vi.unstubAllGlobals();
  });

  it("logs out a protected surface and redirects once to login", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        // No session to restore at mount — this run starts from the login form.
        return Promise.resolve(noSessionCookie());
      }
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(CURRENT_USER));
      }
      if (url.endsWith("/auth/logout")) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    renderSession(
      <>
        <LoginControl />
        <ProtectedSurface />
      </>,
    );

    // The mount-refresh has to settle before the guard can decide anything;
    // until then the surface is busy, not anonymous.
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
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
    // R1: no login/refresh response ever carried a refresh token to read.
    for (const call of fetchImpl.mock.calls) {
      expect(String(call[0])).not.toContain("refresh_token");
    }
  });

  it("restores the session on a reload without ever showing the login form (R5)", async () => {
    // The reload: a brand-new JavaScript runtime with an empty token store and
    // a refresh cookie the browser still holds from the previous page view.
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(CURRENT_USER));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    renderSession(<ProtectedSurface />);

    // Transient `loading`: the guard renders its busy panel, NOT a redirect to
    // `/login`. This is the whole point of R5 — a reload must not look like a
    // logout for the length of one round-trip.
    expect(screen.getByRole("status")).toHaveTextContent("Comprobando sesión…");
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    expect(getSessionTokens()).toEqual({ accessToken: "access" });
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("purges the token, the ['auth','me'] query and calls POST /auth/logout (R4.3, R6.2)", async () => {
    // Pre-existing behavior, re-confirmed against the cookie transport: nothing
    // in `use-logout-mutation.ts` / `session-cache-purge.ts` changed for it.
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(CURRENT_USER));
      }
      if (url.endsWith("/auth/logout")) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    const queryClient = makeQueryClient();

    function LogoutControl() {
      const logoutMutation = useLogoutMutation();
      return (
        <button onClick={() => void logoutMutation.mutateAsync()}>
          logout via mutation
        </button>
      );
    }

    renderSession(
      <>
        <LogoutControl />
        <ProtectedSurface />
      </>,
      queryClient,
    );

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    queryClient.setQueryData(["auth", "me"], CURRENT_USER);

    fireEvent.click(screen.getByRole("button", { name: "logout via mutation" }));

    await waitFor(() =>
      expect(queryClient.getQueryData(["auth", "me"])).toBeUndefined(),
    );
    expect(getSessionTokens()).toBeNull();
    const logoutCall = fetchImpl.mock.calls.find((call: unknown[]) =>
      String(call[0]).endsWith("/auth/logout"),
    );
    expect(logoutCall).toBeDefined();
    expect(logoutCall![1].method).toBe("POST");
    // The cookie is what the server purges, so the request has to carry it.
    expect(logoutCall![1].credentials).toBe("include");
  });

  it("recovers a logout with no cached access token via a fresh refresh (R3, R6.2)", async () => {
    // The store can be empty at logout time — a mount-refresh that never repopulated
    // it, or a session-expired reset — while the refresh cookie the browser holds may
    // still be perfectly live. Losing the request entirely here would leave a
    // revocable session and its cookie behind.
    let refreshCalls = 0;
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(CURRENT_USER));
      }
      if (url.endsWith("/auth/logout")) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    const queryClient = makeQueryClient();

    function LogoutControl() {
      const logoutMutation = useLogoutMutation();
      return (
        <button onClick={() => void logoutMutation.mutateAsync()}>
          logout via mutation
        </button>
      );
    }

    renderSession(
      <>
        <LogoutControl />
        <ProtectedSurface />
      </>,
      queryClient,
    );

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    expect(refreshCalls).toBe(1); // the mount-refresh only, so far

    // A store that has gone empty since mount without the cookie itself changing —
    // e.g. a session-expired reset elsewhere in the app.
    clearSessionTokens();

    fireEvent.click(screen.getByRole("button", { name: "logout via mutation" }));

    await waitFor(() => expect(refreshCalls).toBe(2));
    const logoutCall = await waitFor(() => {
      const call = fetchImpl.mock.calls.find((entry: unknown[]) =>
        String(entry[0]).endsWith("/auth/logout"),
      );
      expect(call).toBeDefined();
      return call!;
    });
    expect(logoutCall[1].method).toBe("POST");
    expect(getSessionTokens()).toBeNull();
  });

  it("drops this tab to anonymous when the refresh 401s after another tab logged out (R6.3)", async () => {
    // Second tab, reloaded (or freshly mounted) after the first tab's logout
    // purged the shared cookie: its mount-refresh gets a 401.
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(noSessionCookie());
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    const sessionExpired = vi.fn();
    const loggedOut = vi.fn();
    const unsubscribeExpired = subscribeToSessionExpired(sessionExpired);
    const unsubscribeLogout = subscribeToLogout(loggedOut);

    try {
      renderSession(<ProtectedSurface />);

      await waitFor(() =>
        expect(router.replace).toHaveBeenCalledWith("/login?returnTo=%2Fdashboard"),
      );
      // `anonymous`, not `expired`: nothing here was ever authenticated, so the
      // guard shows no error panel.
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
      expect(getSessionTokens()).toBeNull();
      // R6.3's "sin afectar a las restantes": a failed restore is local. It
      // broadcasts nothing on the two channels that cross component
      // boundaries, and it does not try to log anyone else out.
      expect(sessionExpired).not.toHaveBeenCalled();
      expect(loggedOut).not.toHaveBeenCalled();
      expect(fetchImpl).toHaveBeenCalledOnce();
    } finally {
      unsubscribeExpired();
      unsubscribeLogout();
    }
  });
});
