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

  it("invalidates provider state when a shared client reports session expiration", async () => {
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

  it("drops the in-memory tokens too, so an expired session keeps no credentials", () => {
    // Two paths reach this listener without `refreshSession` having cleared them: the
    // `SessionInvalidatedError` branch, which skips `clearSessionTokens` when the generation
    // moved underneath it, and the "No refresh token available" early reject, which never had
    // one. Both used to leave the store holding credentials for a session just declared over.
    setSessionTokens({ accessToken: "a", refreshToken: "r" });
    renderAuthWithCache(freshCache());

    act(() => notifySessionExpired());

    expect(getSessionTokens()).toBeNull();
  });

  it("moves the session generation on every purge, which is what invalidates in-flight optimistic snapshots", () => {
    // `notifications-inbox-web` R3.4 depends on this: an optimistic mutation compares the
    // generation in `onError` to decide whether its snapshot still belongs to this session.
    // If a purge left the number where it was, the departing user's cached rows would be
    // written back into the cache that was just emptied to keep them from the next person.
    setSessionTokens({ accessToken: "a", refreshToken: "r" });
    renderAuthWithCache(freshCache());
    const before = getSessionGeneration();

    act(() => notifySessionExpired());

    expect(getSessionGeneration()).not.toBe(before);
  });
});
