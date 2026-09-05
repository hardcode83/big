import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/lib/auth";
import { notifySessionExpired } from "@/lib/api/authenticated-client";
import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
import { markSessionPresent } from "@/lib/auth/session-presence-cookie";
import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { makeQueryClient } from "@/lib/query/query-client";
import { act, fireEvent, render, screen, waitFor } from "@/test/render";

function readPresenceCookie(): string | null {
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  const match = cookies.find((entry) => entry.startsWith(`${SESSION_PRESENT_COOKIE}=`));
  return match ? match.slice(SESSION_PRESENT_COOKIE.length + 1) : null;
}

function clearAllCookies(): void {
  document.cookie.split("; ").forEach((entry) => {
    const name = entry.split("=")[0];
    if (name) {
      document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
    }
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/**
 * The 401 the backend answers with when the `httpOnly` refresh cookie is
 * absent, expired or already rotated. Every test that does NOT exercise the
 * silent mount-refresh still needs it: `AuthProvider` now fires one
 * `POST /auth/refresh` per mount into an empty session store (R5.1), so a
 * `fetch` stub that does not answer that call leaves the provider hanging on
 * `loading` — or, worse, hands the mount-refresh a response meant for the
 * login that follows.
 */
function noSessionCookie(): Response {
  return jsonResponse(
    { error: { code: "UNAUTHENTICATED", message: "No refresh cookie" } },
    401,
  );
}

const USER_ONE = {
  id: "user-1",
  email: "user@example.com",
  name: "User",
  preferred_language: "es",
  role: "TENANT_OWNER",
  tenant_id: "tenant-1",
};

const TOKEN_PAIR = {
  access_token: "access",
  token_type: "bearer",
  expires_in: 900,
};

function Probe() {
  const { status, user } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.email ?? "none"}</span>
      <span data-testid="role">{user?.role ?? "none"}</span>
      <span data-testid="tenant">{user?.tenant_id ?? "none"}</span>
    </div>
  );
}

function renderAuth() {
  return render(
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
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </RuntimeConfigProvider>,
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    clearAllCookies();
  });

  afterEach(() => {
    clearSessionTokens();
    clearAllCookies();
    vi.unstubAllGlobals();
  });

  it("restores the session from the refresh cookie at mount (R5.1, R5.2)", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(USER_ONE));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    renderAuth();

    // R5.1: the transient state is visible before the promise settles — a
    // consumer that read `anonymous` here would bounce the user to `/login`.
    expect(screen.getByTestId("status")).toHaveTextContent("loading");

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
    expect(screen.getByTestId("role")).toHaveTextContent("TENANT_OWNER");
    expect(screen.getByTestId("tenant")).toHaveTextContent("tenant-1");
    expect(getSessionTokens()).toEqual({ accessToken: "access" });

    const [refreshUrl, refreshInit] = fetchImpl.mock.calls[0];
    expect(refreshUrl).toBe("/api/v1/auth/refresh");
    expect(refreshInit.method).toBe("POST");
    // The cookie is the whole credential: nothing in the body, no bearer.
    expect(refreshInit.credentials).toBe("include");
    expect(refreshInit.body).toBeUndefined();
    expect(new Headers(refreshInit.headers).get("Authorization")).toBeNull();

    const meCall = fetchImpl.mock.calls.find((call: unknown[]) =>
      String(call[0]).endsWith("/auth/me"),
    );
    expect(meCall).toBeDefined();
    expect(new Headers(meCall![1].headers).get("Authorization")).toBe(
      "Bearer access",
    );
  });

  it("resolves anonymous with no visible error when the refresh cookie is gone (R5.3)", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(noSessionCookie());
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    // No `error` status, no `/auth/me` attempt, no credentials left behind.
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(getSessionTokens()).toBeNull();
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("resolves anonymous when the network drops the mount-refresh (R5.3)", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchImpl);

    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    expect(getSessionTokens()).toBeNull();
  });

  it("leaves no access token behind when the mount-refresh works but /auth/me does not (R5.3)", async () => {
    // The half-restored case: the refresh cookie was still good, so an access
    // token really did land in the store, and then the identity call failed.
    // Resolving `anonymous` while the store still holds usable credentials
    // would leave a bare token backing nobody — every later request would go
    // out authenticated under a session the provider believes does not exist.
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    renderAuth();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(getSessionTokens()).toBeNull();
  });

  it("drops a mount-refresh token that resolves after the session was torn down (D8)", async () => {
    // The generation guard in `runMountRefresh`, mirroring
    // `refresh-coordinator.ts:46`. A slow `/auth/refresh` that is still in
    // flight when the user logs out must not install its token afterwards:
    // the store is module-level, so that write would silently reinstate live
    // credentials for a session the app has already torn down.
    let resolveRefresh!: (response: Response) => void;
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return new Promise<Response>((resolve) => {
          resolveRefresh = resolve;
        });
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(USER_ONE));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    function LogoutProbe() {
      const { logout } = useAuth();
      return <button onClick={() => void logout()}>logout</button>;
    }

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
        <AuthProvider>
          <LogoutProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    await waitFor(() =>
      expect(fetchImpl).toHaveBeenCalledWith(
        "/api/v1/auth/refresh",
        expect.anything(),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "logout" }));
    resolveRefresh(jsonResponse(TOKEN_PAIR));

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("anonymous"),
    );
    expect(getSessionTokens()).toBeNull();
    // Dropped before `setSessionTokens`, so the identity call never happens
    // either — nothing downstream of the guard runs.
    const meCalls = fetchImpl.mock.calls.filter((call: unknown[]) =>
      String(call[0]).endsWith("/auth/me"),
    );
    expect(meCalls).toHaveLength(0);
  });

  it("keeps a concurrent login's tokens when the mount-refresh's own /auth/me fails afterwards (D8)", async () => {
    // The mirror of the guard above, on the failure path. The mount-refresh
    // installs its token, then its `/auth/me` fails — but by then a `login()`
    // has completed and put a NEWER session's token in the same module-level
    // store. Clearing unconditionally there would wipe live credentials that
    // have nothing to do with this refresh.
    let rejectMountMe!: (reason: unknown) => void;
    let meCallCount = 0;
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(
          jsonResponse({ ...TOKEN_PAIR, access_token: "stale-access" }),
        );
      }
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(
          jsonResponse({ ...TOKEN_PAIR, access_token: "newer-access" }),
        );
      }
      if (url.endsWith("/auth/me")) {
        meCallCount += 1;
        // The first `/auth/me` is the mount-refresh's, held open until the
        // login has finished; the second is the login's own.
        if (meCallCount === 1) {
          return new Promise<Response>((_resolve, reject) => {
            rejectMountMe = reject;
          });
        }
        return Promise.resolve(jsonResponse(USER_ONE));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    function LoginProbe() {
      const { login } = useAuth();
      return (
        <button onClick={() => void login("user@example.com", "pw")}>login</button>
      );
    }

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
        <AuthProvider>
          <LoginProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    // The mount-refresh has installed its own token and is now blocked on
    // `/auth/me`.
    await waitFor(() => expect(meCallCount).toBe(1));
    expect(getSessionTokens()?.accessToken).toBe("stale-access");

    fireEvent.click(screen.getByRole("button", { name: "login" }));
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
    expect(getSessionTokens()?.accessToken).toBe("newer-access");

    // Only now does the mount-refresh's identity call fail.
    await act(async () => {
      rejectMountMe(new TypeError("Failed to fetch"));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    // The newer session survives: the stale token this branch wanted to drop
    // was already overwritten by the login's write.
    expect(getSessionTokens()?.accessToken).toBe("newer-access");
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
  });

  it("shares one mount-refresh round-trip across providers mounted in the same tick (R5.4)", async () => {
    // Stands in for React StrictMode's dev double-invoke and for two routes
    // each mounting their own guarded subtree: the second mount must join the
    // in-flight promise instead of rotating the refresh cookie a second time.
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(USER_ONE));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    const config = {
      apiBaseUrl: "",
      appEnv: "test",
      defaultLocale: "es" as const,
      featureFlags: {},
      appVersion: "",
      buildCommitShort: "",
      appUrl: "",
    };
    render(
      <RuntimeConfigProvider config={config}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    await waitFor(() => {
      for (const node of screen.getAllByTestId("status")) {
        expect(node).toHaveTextContent("authenticated");
      }
    });
    expect(screen.getAllByTestId("status")).toHaveLength(2);

    const refreshCalls = fetchImpl.mock.calls.filter((call: unknown[]) =>
      String(call[0]).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
    // The joiner reads the identity off the shared promise rather than asking
    // `/auth/me` again — one mount-refresh means one round-trip, not one call.
    const meCalls = fetchImpl.mock.calls.filter((call: unknown[]) =>
      String(call[0]).endsWith("/auth/me"),
    );
    expect(meCalls).toHaveLength(1);
  });

  it("skips the mount-refresh when the runtime already holds an access token", () => {
    setSessionTokens({ accessToken: "access" });
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);

    renderAuth();

    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("exposes login identity and keeps the token pair in memory", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(noSessionCookie());
      }
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(USER_ONE));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    function LoginProbe() {
      const { login } = useAuth();
      return <button onClick={() => void login("user@example.com", "secret")}>login</button>;
    }

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
        <AuthProvider>
          <LoginProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "login" }));

    expect(await screen.findByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
    expect(screen.getByTestId("role")).toHaveTextContent("TENANT_OWNER");
    expect(screen.getByTestId("tenant")).toHaveTextContent("tenant-1");
    expect(getSessionTokens()).toEqual({ accessToken: "access" });
    expect(readPresenceCookie()).toBe("1");
    const meCall = fetchImpl.mock.calls.find((call: unknown[]) =>
      String(call[0]).endsWith("/auth/me"),
    );
    expect(meCall).toBeDefined();
    expect(new Headers(meCall![1].headers).get("Authorization")).toBe(
      "Bearer access",
    );
  });

  it("clears the pair and exposes an error state when login fails", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: "INVALID_CREDENTIALS", message: "invalid" },
        }),
        { status: 401 },
      ),
    );
    vi.stubGlobal("fetch", fetchImpl);

    function LoginProbe() {
      const { login } = useAuth();
      return (
        <button onClick={() => void login("user@example.com", "wrong").catch(() => undefined)}>
          login
        </button>
      );
    }

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
        <AuthProvider>
          <LoginProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "login" }));

    expect(await screen.findByTestId("status")).toHaveTextContent("error");
    expect(getSessionTokens()).toBeNull();
    expect(readPresenceCookie()).toBeNull();
  });

  it("invalidates provider state when a shared client reports session expiration", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(noSessionCookie());
      }
      if (url.endsWith("/auth/login")) {
        return Promise.resolve(jsonResponse(TOKEN_PAIR));
      }
      if (url.endsWith("/auth/me")) {
        return Promise.resolve(jsonResponse(USER_ONE));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    function LoginProbe() {
      const { login } = useAuth();
      return <button onClick={() => void login("user@example.com", "secret")}>login</button>;
    }

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
        <AuthProvider>
          <LoginProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByTestId("status")).toHaveTextContent("authenticated");

    act(() => notifySessionExpired());

    expect(screen.getByTestId("status")).toHaveTextContent("expired");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(readPresenceCookie()).toBeNull();
  });

  it("logs out locally even when the backend logout is unavailable", async () => {
    // `useAuth().logout()` runs the local-state purge only (F5 / review);
    // the server round-trip is owned by `useLogoutMutation`. The "backend
    // unavailable" path that was previously asserted on this test now
    // belongs to `useLogoutMutation`'s own tests.
    setSessionTokens({ accessToken: "access" });
    markSessionPresent();

    function LogoutProbe() {
      const { logout } = useAuth();
      return <button onClick={() => void logout()}>logout</button>;
    }

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
        <AuthProvider>
          <LogoutProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    expect(await screen.findByTestId("status")).toHaveTextContent("anonymous");
    expect(getSessionTokens()).toBeNull();
    expect(readPresenceCookie()).toBeNull();
  });

  it("invalidates an in-flight refresh when logout clears the session", async () => {
    setSessionTokens({ accessToken: "access" });
    let resolveRefresh!: (response: Response) => void;
    const fetchImpl = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return new Promise<Response>((resolve) => {
          resolveRefresh = resolve;
        });
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetchImpl);

    function SessionProbe() {
      const { logout, refresh } = useAuth();
      return (
        <>
          <button onClick={() => void refresh()}>refresh</button>
          <button onClick={() => void logout()}>logout</button>
        </>
      );
    }

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
        <AuthProvider>
          <SessionProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "refresh" }));
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/auth/refresh",
      expect.anything(),
    ));
    fireEvent.click(screen.getByRole("button", { name: "logout" }));
    resolveRefresh(new Response(JSON.stringify({
      access_token: "late-access",
      refresh_token: "late-refresh",
      token_type: "bearer",
      expires_in: 900,
    }), { status: 200 }));

    await screen.findByTestId("status");
    expect(getSessionTokens()).toBeNull();
  });

  it("reflects one shared refresh failure without request-owned navigation", async () => {
    setSessionTokens({ accessToken: "access" });
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "expired" } }),
        { status: 401 },
      ),
    );
    vi.stubGlobal("fetch", fetchImpl);

    function RefreshProbe() {
      const { refresh } = useAuth();
      return <button onClick={() => void Promise.all([refresh(), refresh()])}>refresh</button>;
    }

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
        <AuthProvider>
          <RefreshProbe />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "refresh" }));

    expect(await screen.findByTestId("status")).toHaveTextContent("expired");
    expect(fetchImpl).toHaveBeenCalledOnce();
    expect(getSessionTokens()).toBeNull();
  });
});

/**
 * Cache-invariant tests (design D5): every identity transition in `AuthProvider`
 * must purge the singleton `QueryClient` so that the next user logged into the
 * same tab cannot read cached data from the previous one. The QueryClient
 * returned by `getQueryClient()` is replaced with a fresh per-test instance so
 * the assertions only see what the test wrote, and so a future HMR or shared
 * state in the browser singleton cannot bleed across tests.
 */
const cacheClientRef = vi.hoisted(() => ({
  current: null as QueryClient | null,
}));

vi.mock("@/lib/query/query-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/query/query-client")>();
  return {
    ...actual,
    // When a cache-invariant test has registered a mock client, return that.
    // Otherwise fall back to the real singleton so pre-existing tests
    // (which never touched the cache) keep working after `AuthProvider`
    // started calling `purgeSessionCache()` at every identity transition.
    getQueryClient: () => cacheClientRef.current ?? actual.getQueryClient(),
  };
});

function freshCache(): QueryClient {
  cacheClientRef.current = makeQueryClient();
  return cacheClientRef.current;
}

function renderAuthWithCache(cache: QueryClient, inner?: ReactNode) {
  return render(
    <RuntimeConfigProvider
      config={{
        apiBaseUrl: "",
        appUrl: "",
        appEnv: "test",
        defaultLocale: "es",
        featureFlags: {},
        appVersion: "",
        buildCommitShort: "",
      }}
    >
      <QueryClientProvider client={cache}>
        <AuthProvider>
          <Probe />
          {inner}
        </AuthProvider>
      </QueryClientProvider>
    </RuntimeConfigProvider>,
  );
}

/**
 * Two consecutive logins in the same tab: `user-1@example.com` and then
 * `user-2@example.com`, the second one landing in `secondTenantId`. Dispatches
 * on URL rather than on call order because the silent mount-refresh (R5.1)
 * fires its own `POST /auth/refresh` before either login — a positional
 * `mockResolvedValueOnce` chain would hand the mount-refresh the first login's
 * token pair.
 */
function userSwapFetch(secondTenantId: string) {
  let meCalls = 0;
  return vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/auth/refresh")) {
      return Promise.resolve(noSessionCookie());
    }
    if (url.endsWith("/auth/login")) {
      return Promise.resolve(jsonResponse(TOKEN_PAIR));
    }
    if (url.endsWith("/auth/me")) {
      meCalls += 1;
      return Promise.resolve(
        jsonResponse(
          meCalls === 1
            ? {
                id: "user-1",
                email: "user-1@example.com",
                name: "User One",
                preferred_language: "es",
                role: "TENANT_OWNER",
                tenant_id: "tenant-1",
              }
            : {
                id: "user-2",
                email: "user-2@example.com",
                name: "User Two",
                preferred_language: "es",
                role: "TENANT_OWNER",
                tenant_id: secondTenantId,
              },
        ),
      );
    }
    throw new Error(`Unexpected request: ${url}`);
  });
}

describe("AuthProvider — query cache purge on identity transitions", () => {
  afterEach(() => {
    cacheClientRef.current = null;
  });

  it("purges the query cache when logout completes (R4.1)", async () => {
    const cache = freshCache();
    setSessionTokens({ accessToken: "access" });
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchImpl);

    function LogoutProbe() {
      const { logout } = useAuth();
      return <button onClick={() => void logout()}>logout</button>;
    }

    renderAuthWithCache(cache, <LogoutProbe />);
    cache.setQueryData(["tenant", "t-1", "properties"], [{ id: "p-1" }]);

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    await screen.findByTestId("status");
    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("purges the query cache even when the POST /auth/logout fails (R1.2)", async () => {
    const cache = freshCache();
    setSessionTokens({ accessToken: "access" });
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "expired" } }),
        { status: 401 },
      ),
    );
    vi.stubGlobal("fetch", fetchImpl);

    function LogoutProbe() {
      const { logout } = useAuth();
      return <button onClick={() => void logout()}>logout</button>;
    }

    renderAuthWithCache(cache, <LogoutProbe />);
    cache.setQueryData(["tenant", "t-1", "properties"], [{ id: "p-1" }]);

    fireEvent.click(screen.getByRole("button", { name: "logout" }));

    await screen.findByTestId("status");
    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("purges the query cache when a same-tenant user swap completes (R5.1)", async () => {
    const cache = freshCache();
    vi.stubGlobal("fetch", userSwapFetch("tenant-1"));

    function LoginProbe() {
      const { login } = useAuth();
      return (
        <button
          onClick={() =>
            void login("user-1@example.com", "secret").then(() =>
              login("user-2@example.com", "secret"),
            )
          }
        >
          login
        </button>
      );
    }

    renderAuthWithCache(cache, <LoginProbe />);
    cache.setQueryData(["tenant", "tenant-1", "properties"], [{ id: "p-1" }]);

    fireEvent.click(screen.getByRole("button", { name: "login" }));

    await screen.findByTestId("status");
    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("purges the query cache when a cross-tenant user swap completes (R5.1 — OQ3)", async () => {
    const cache = freshCache();
    vi.stubGlobal("fetch", userSwapFetch("tenant-2"));

    function LoginProbe() {
      const { login } = useAuth();
      return (
        <button
          onClick={() =>
            void login("user-1@example.com", "secret").then(() =>
              login("user-2@example.com", "secret"),
            )
          }
        >
          login
        </button>
      );
    }

    renderAuthWithCache(cache, <LoginProbe />);
    cache.setQueryData(["tenant", "tenant-1", "properties"], [{ id: "p-1" }]);

    fireEvent.click(screen.getByRole("button", { name: "login" }));

    await screen.findByTestId("status");
    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("purges the query cache when refresh fails and falls back to expired (R2.1)", async () => {
    const cache = freshCache();
    setSessionTokens({ accessToken: "access" });
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "expired" } }),
        { status: 401 },
      ),
    );
    vi.stubGlobal("fetch", fetchImpl);

    function RefreshProbe() {
      const { refresh } = useAuth();
      return <button onClick={() => void refresh()}>refresh</button>;
    }

    renderAuthWithCache(cache, <RefreshProbe />);
    cache.setQueryData(["tenant", "tenant-1", "properties"], [{ id: "p-1" }]);

    fireEvent.click(screen.getByRole("button", { name: "refresh" }));

    await screen.findByTestId("status");
    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("purges the query cache when the session-expired listener fires (R5.2)", async () => {
    const cache = freshCache();
    // The provider mounts with an empty store, so it also fires the silent
    // mount-refresh; answer it explicitly instead of letting the test inherit
    // whatever stub the previous one happened to leave behind.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(noSessionCookie()),
    );
    renderAuthWithCache(cache);
    cache.setQueryData(["tenant", "tenant-1", "properties"], [{ id: "p-1" }]);

    act(() => notifySessionExpired());

    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("drops the in-memory tokens too, so an expired session keeps no credentials", () => {
    // Two paths reach this listener without `refreshSession` having cleared them: the
    // `SessionInvalidatedError` branch, which skips `clearSessionTokens` when the generation
    // moved underneath it, and the "No refresh token available" early reject, which never had
    // one. Both used to leave the store holding credentials for a session just declared over.
    setSessionTokens({ accessToken: "a" });
    renderAuthWithCache(freshCache());

    act(() => notifySessionExpired());

    expect(getSessionTokens()).toBeNull();
  });

  it("moves the session generation on every purge, which is what invalidates in-flight optimistic snapshots", () => {
    // `notifications-inbox-web` R3.4 depends on this: an optimistic mutation compares the
    // generation in `onError` to decide whether its snapshot still belongs to this session.
    // If a purge left the number where it was, the departing user's cached rows would be
    // written back into the cache that was just emptied to keep them from the next person.
    setSessionTokens({ accessToken: "a" });
    renderAuthWithCache(freshCache());
    const before = getSessionGeneration();

    act(() => notifySessionExpired());

    expect(getSessionGeneration()).not.toBe(before);
  });
});
