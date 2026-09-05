import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/lib/auth";
import { notifySessionExpired } from "@/lib/api/authenticated-client";
import {
  clearSessionTokens,
  getSessionGeneration,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
import { refreshSession } from "@/lib/auth/refresh-coordinator";
import { purgeSessionCache } from "@/lib/auth/session-cache-purge";
import { markSessionPresent } from "@/lib/auth/session-presence-cookie";
import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { makeQueryClient } from "@/lib/query/query-client";
import { act, fireEvent, render, screen } from "@/test/render";

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

  it("starts anonymous without attempting session restoration", () => {
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);

    renderAuth();

    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("exposes login identity and keeps the token pair in memory", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "user@example.com",
            name: "User",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      );
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
    expect(getSessionTokens()).toEqual({ accessToken: "access", refreshToken: "refresh" });
    expect(readPresenceCookie()).toBe("1");
    expect(new Headers(fetchImpl.mock.calls[1][1].headers).get("Authorization")).toBe(
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

  it("does not let a stale in-flight refresh resurrect tokens after a failed login (R1.4 bare-clear site)", async () => {
    // A refresh started under the previous session is still in flight when the user
    // attempts (and fails) a new login. Before the fix, login()'s catch called
    // clearSessionTokens() without bumping sessionGeneration, so the stale refresh's
    // `.then` would see an unchanged generation and resurrect a token pair into a
    // session the app had just torn down.
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });

    let resolveStaleRefresh!: (tokens: { accessToken: string; refreshToken: string }) => void;
    const staleRefresh = refreshSession(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
          resolveStaleRefresh = resolve;
        }),
    );

    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: "INVALID_CREDENTIALS", message: "invalid" } }),
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

    // The stale refresh finally resolves. Its captured generation must no longer match
    // (login()'s catch bumped it), so the coordinator rejects instead of resurrecting.
    resolveStaleRefresh({ accessToken: "rotated-access", refreshToken: "rotated-refresh" });

    await expect(staleRefresh).rejects.toThrow("Session was invalidated");
    expect(getSessionTokens()).toBeNull();
  });

  it("keeps the new login's tokens when SessionInvalidatedError lands after a winning login (R4.2)", async () => {
    // R4.2 interleaving: a refresh started under user A is still in flight when user B's
    // login completes. The refresh-coordinator detects the generation moved and throws
    // `SessionInvalidatedError` without touching the new tokens. The onUnauthorized
    // callback in `authenticated-client.ts` then calls `notifySessionExpired()`, which
    // routes through this listener. With D5, the listener finds the token store holding
    // the login pair and returns early — login tokens survive, status stays
    // `"authenticated"`.
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });

    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "new-access",
            refresh_token: "new-refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "user@example.com",
            name: "User",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      );
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

    // Kick off the in-flight refresh *before* login — it captures the current generation
    // (the one `setSessionTokens({old...})` just installed). The promise stays pending
    // while login runs, mirroring the production race where the apiClient's
    // onUnauthorized is mid-flight against user A's tokens when user B logs in.
    let resolveOldRefresh!: (tokens: { accessToken: string; refreshToken: string }) => void;
    const lateRefresh = refreshSession(
      () =>
        new Promise<{ accessToken: string; refreshToken: string }>((resolve) => {
          resolveOldRefresh = resolve;
        }),
    );

    // Login installs the new pair (generation advances by 1), `status` → `"authenticated"`.
    fireEvent.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByTestId("status")).toHaveTextContent("authenticated");
    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });

    // The in-flight refresh finally returns 200. The coordinator's `.then` sees the
    // generation moved (login incremented it) and throws `SessionInvalidatedError`.
    resolveOldRefresh({ accessToken: "rotated-access", refreshToken: "rotated-refresh" });

    await expect(lateRefresh).rejects.toThrow("Session was invalidated");
    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });

    // The next API call after the failed refresh would 401 and trigger
    // `notifySessionExpired()` through `onUnauthorized`. We fire it manually here to
    // observe the listener in isolation, with no intervening React state churn.
    act(() => notifySessionExpired());

    // D5: listener returns early because `getSessionTokens()` is non-null.
    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
    expect(readPresenceCookie()).toBe("1");
  });

  it("lets the listener clear the session when 'No refresh token available' lands with no live tokens, but login wins when tokens are live (R4.3)", async () => {
    // R4.3 has two variants. Both arrive at the listener without going through the
    // coordinator's guard: in one, the token store is non-null because a fresh login
    // already installed its pair (login wins); in the other, the store is null because
    // the coordinator's guard or an upstream path cleared it before the listener fired.
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });

    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "new-access",
            refresh_token: "new-refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "user@example.com",
            name: "User",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      );
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
    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });

    // Sub-scenario A — login wins: the token store still holds the login pair, so the
    // listener returns early and the session stays as `login()` installed it.
    act(() => notifySessionExpired());
    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");

    // Sub-scenario B — the "No refresh token available" path: the coordinator's guard or
    // an upstream path nulled the tokens before the listener fired. React state still says
    // `"authenticated"`, but `getSessionTokens()` is null at entry, so the listener runs
    // the cleanup completo and resets `user` and `status`.
    clearSessionTokens();
    act(() => notifySessionExpired());
    expect(getSessionTokens()).toBeNull();
    expect(screen.getByTestId("status")).toHaveTextContent("expired");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(readPresenceCookie()).toBeNull();
  });

  it("preserves the new login's tokens when a shared client reports session expiration mid-session (D5 / R3.2)", async () => {
    // After D5: a `login()` that completes installs its tokens and pushes `status` to
    // `"authenticated"`. When `notifySessionExpired()` arrives afterwards, the listener
    // finds the token store already holding the new pair, returns early, and leaves the
    // session as `login()` installed it. This is the production race that R4.2 / R4.3
    // exercise end-to-end — this test isolates the listener half of it.
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "user@example.com",
            name: "User",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchImpl);

    function LoginProbe() {
      const { login } = useAuth();
      return <button onClick={() => void login("user@example.com", "secret")}>login</button>;
    }

    const cache = freshCache();
    cache.setQueryData(["tenant", "tenant-1", "properties"], [{ id: "p-1" }]);

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
        <QueryClientProvider client={cache}>
          <AuthProvider>
            <LoginProbe />
            <Probe />
          </AuthProvider>
        </QueryClientProvider>
      </RuntimeConfigProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByTestId("status")).toHaveTextContent("authenticated");

    act(() => notifySessionExpired());

    // Login tokens survive — the listener returned early on `getSessionTokens() !== null`.
    expect(getSessionTokens()).toEqual({ accessToken: "access", refreshToken: "refresh" });
    expect(readPresenceCookie()).toBe("1");
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
    // The listener did reach `purgeSessionCache()` — the singleton `QueryClient` is empty
    // even though `login()` did not write to it.
    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("clears the session when a shared client reports session expiration and no tokens are live (D5 fallback)", async () => {
    // Companion to the test above: when `notifySessionExpired()` arrives while the token
    // store is empty (the production path where `refresh-coordinator`'s guard already
    // nulled tokens but React state still says `"authenticated"`), the listener runs
    // the cleanup completo. This is the path `"No refresh token available"` takes when
    // it bypasses the coordinator and lands here directly.
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
    markSessionPresent();

    renderAuth();

    clearSessionTokens();

    act(() => notifySessionExpired());

    expect(getSessionTokens()).toBeNull();
    expect(screen.getByTestId("status")).toHaveTextContent("expired");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(readPresenceCookie()).toBeNull();
  });

  it("logs out locally even when the backend logout is unavailable", async () => {
    // `useAuth().logout()` runs the local-state purge only (F5 / review);
    // the server round-trip is owned by `useLogoutMutation`. The "backend
    // unavailable" path that was previously asserted on this test now
    // belongs to `useLogoutMutation`'s own tests.
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
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
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
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
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
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

  it("does not clobber a winning login when refresh()'s own catch settles after the race (security review, third round)", async () => {
    // Same defect class as D5 (the listener) and D7 (authenticated-client.ts's
    // onUnauthorized) — refresh()'s own catch had no getSessionTokens() === null guard,
    // so a stale refresh started under the departing session could still force
    // status/user to "expired" after a newer login had already won.
    setSessionTokens({ accessToken: "old-access", refreshToken: "old-refresh" });

    let resolveStaleRefresh!: (response: Response) => void;
    const fetchImpl = vi.fn((url: RequestInfo | URL) => {
      const path = String(url);
      if (path.includes("/api/v1/auth/refresh")) {
        return new Promise<Response>((resolve) => {
          resolveStaleRefresh = resolve;
        });
      }
      if (path.includes("/api/v1/auth/login")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              access_token: "new-access",
              refresh_token: "new-refresh",
              token_type: "bearer",
              expires_in: 900,
            }),
            { status: 200 },
          ),
        );
      }
      if (path.includes("/api/v1/auth/me")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              id: "user-1",
              email: "user@example.com",
              name: "User",
              preferred_language: "es",
              role: "TENANT_OWNER",
              tenant_id: "tenant-1",
            }),
            { status: 200 },
          ),
        );
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    vi.stubGlobal("fetch", fetchImpl);

    // Capture the hook's callbacks directly so the stale `refresh()` call's own promise
    // can be awaited below — a call-count-based waitFor is unreliable here because
    // login()'s two fetches already bring the total to 3 before the stale refresh's
    // rejection has propagated through refresh()'s catch. The assignment happens inside
    // an effect (not during render) so it stays a pure render per the hooks rules.
    const callbacksRef: {
      refresh: (() => Promise<boolean>) | null;
      login: ((email: string, password: string) => Promise<unknown>) | null;
    } = { refresh: null, login: null };

    function Probes() {
      const { login, refresh } = useAuth();
      useEffect(() => {
        callbacksRef.refresh = refresh;
        callbacksRef.login = login;
      });
      return null;
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
          <Probes />
          <Probe />
        </AuthProvider>
      </RuntimeConfigProvider>,
    );

    // The old session's refresh() starts; its fetch to /auth/refresh stays pending.
    let stalePending!: Promise<boolean>;
    act(() => {
      stalePending = callbacksRef.refresh!();
    });
    await vi.waitFor(() =>
      expect(fetchImpl).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/auth/refresh"),
        expect.anything(),
      ),
    );

    // A new login wins the race while the stale refresh is still in flight.
    await act(async () => {
      await callbacksRef.login!("user@example.com", "secret");
    });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });

    // The stale refresh finally settles as a failure (e.g. the old refresh token was
    // revoked). refresh()'s own catch must not clobber the winning login's session.
    // Awaiting `stalePending` itself guarantees the catch's state updates have landed.
    await act(async () => {
      resolveStaleRefresh(
        new Response(
          JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "revoked" } }),
          { status: 401 },
        ),
      );
      await stalePending;
    });

    expect(getSessionTokens()).toEqual({ accessToken: "new-access", refreshToken: "new-refresh" });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
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

describe("AuthProvider — query cache purge on identity transitions", () => {
  afterEach(() => {
    cacheClientRef.current = null;
  });

  it("purges the query cache when logout completes (R4.1)", async () => {
    const cache = freshCache();
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
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
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
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
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "user-1@example.com",
            name: "User One",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-2",
            email: "user-2@example.com",
            name: "User Two",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchImpl);

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
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-1",
            email: "user-1@example.com",
            name: "User One",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-1",
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access",
            refresh_token: "refresh",
            token_type: "bearer",
            expires_in: 900,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "user-2",
            email: "user-2@example.com",
            name: "User Two",
            preferred_language: "es",
            role: "TENANT_OWNER",
            tenant_id: "tenant-2",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchImpl);

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
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
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
    renderAuthWithCache(cache);
    cache.setQueryData(["tenant", "tenant-1", "properties"], [{ id: "p-1" }]);

    act(() => notifySessionExpired());

    expect(cache.getQueryCache().getAll()).toHaveLength(0);
  });

  it("moves the session generation on every purge, which is what invalidates in-flight optimistic snapshots", () => {
    // The bump lives in `purgeSessionCache()` (D1 / R1.1) — not in this listener — so every
    // purge that runs through this codepath advances the counter. `notifications-inbox-web`
    // R3.4 depends on this: an optimistic mutation compares the generation in `onError`
    // against the value captured at `onMutate` to decide whether its snapshot still belongs
    // to this session. If a purge left the number where it was, the departing user's cached
    // rows would be written back into the cache that was just emptied to keep them from
    // the next person. The listener here calls `purgeSessionCache()` (D5 / section 2),
    // which is what triggers the bump — the body of this test stays unchanged for that
    // reason, and the assertion below holds because the listener still reaches the purge.
    setSessionTokens({ accessToken: "a", refreshToken: "r" });
    renderAuthWithCache(freshCache());
    const before = getSessionGeneration();

    act(() => notifySessionExpired());

    expect(getSessionGeneration()).not.toBe(before);
  });
});
