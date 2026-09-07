import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/lib/auth";
import { useLogoutMutation } from "@/features/auth/hooks/use-logout-mutation";
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
import { notifyLogout } from "@/lib/auth/logout-event";
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
    // Tears down the session mid-flight the way the real `useLogoutMutation`
    // flow does: clear the store, then tell `AuthProvider` (`notifyLogout()`).
    act(() => {
      clearSessionTokens();
      notifyLogout();
    });
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

  it("does not let a stale in-flight refresh resurrect tokens after a failed login (R1.4 bare-clear site)", async () => {
    // A refresh started under the previous session is still in flight when the user
    // attempts (and fails) a new login. Before the fix, login()'s catch called
    // clearSessionTokens() without bumping sessionGeneration, so the stale refresh's
    // `.then` would see an unchanged generation and resurrect a token pair into a
    // session the app had just torn down.
    setSessionTokens({ accessToken: "old-access" });

    let resolveStaleRefresh!: (tokens: { accessToken: string }) => void;
    const staleRefresh = refreshSession(
      () =>
        new Promise<{ accessToken: string }>((resolve) => {
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
    resolveStaleRefresh({ accessToken: "rotated-access" });

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
    setSessionTokens({ accessToken: "old-access" });

    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "new-access",
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
    let resolveOldRefresh!: (tokens: { accessToken: string }) => void;
    const lateRefresh = refreshSession(
      () =>
        new Promise<{ accessToken: string }>((resolve) => {
          resolveOldRefresh = resolve;
        }),
    );

    // Login installs the new pair (generation advances by 1), `status` → `"authenticated"`.
    fireEvent.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByTestId("status")).toHaveTextContent("authenticated");
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });

    // The in-flight refresh finally returns 200. The coordinator's `.then` sees the
    // generation moved (login incremented it) and throws `SessionInvalidatedError`.
    resolveOldRefresh({ accessToken: "rotated-access" });

    await expect(lateRefresh).rejects.toThrow("Session was invalidated");
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });

    // The next API call after the failed refresh would 401 and trigger
    // `notifySessionExpired()` through `onUnauthorized`. We fire it manually here to
    // observe the listener in isolation, with no intervening React state churn.
    act(() => notifySessionExpired());

    // D5: listener returns early because `getSessionTokens()` is non-null.
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");
    expect(readPresenceCookie()).toBe("1");
  });

  it("lets the listener clear the session when it lands with no live tokens, but login wins when tokens are live (R4.3)", async () => {
    // R4.3 has two variants. Both arrive at the listener without going through the
    // coordinator's guard: in one, the token store is non-null because a fresh login
    // already installed its pair (login wins); in the other, the store is null because
    // the coordinator's guard or an upstream path cleared it before the listener fired.
    setSessionTokens({ accessToken: "old-access" });

    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "new-access",
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
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });

    // Sub-scenario A — login wins: the token store still holds the login pair, so the
    // listener returns early and the session stays as `login()` installed it.
    act(() => notifySessionExpired());
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user@example.com");

    // Sub-scenario B — tokens already cleared: the coordinator's guard or
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
    //
    // The provider mounts with an empty store, so it also fires the silent
    // mount-refresh (R5.1) — the fetch stub must dispatch on URL rather than
    // use a positional `mockResolvedValueOnce` chain, or the mount-refresh
    // would consume the response meant for `login()`.
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
    expect(getSessionTokens()).toEqual({ accessToken: "access" });
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
    // the cleanup completo.
    setSessionTokens({ accessToken: "access" });
    markSessionPresent();

    renderAuth();

    clearSessionTokens();

    act(() => notifySessionExpired());

    expect(getSessionTokens()).toBeNull();
    expect(screen.getByTestId("status")).toHaveTextContent("expired");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(readPresenceCookie()).toBeNull();
  });

  it("invalidates an in-flight refresh when logout clears the session", async () => {
    // Drives the clear the way the real `useLogoutMutation` flow does —
    // `clearSessionTokens()` then `notifyLogout()` — instead of through
    // `useAuth()`, which no longer exposes a `logout` method (the local-only
    // wrapper was removed; the real flow lives in `useLogoutMutation`).
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

    function RefreshProbe() {
      const { refresh } = useAuth();
      return <button onClick={() => void refresh()}>refresh</button>;
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
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledWith(
      "/api/v1/auth/refresh",
      expect.anything(),
    ));
    act(() => {
      clearSessionTokens();
      notifyLogout();
    });
    resolveRefresh(new Response(JSON.stringify({
      access_token: "late-access",
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

  it("does not clobber a winning login when refresh()'s own catch settles after the race (security review, third round)", async () => {
    // Same defect class as D5 (the listener) and D7 (authenticated-client.ts's
    // onUnauthorized) — refresh()'s own catch had no getSessionTokens() === null guard,
    // so a stale refresh started under the departing session could still force
    // status/user to "expired" after a newer login had already won.
    setSessionTokens({ accessToken: "old-access" });

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
    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });

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

    expect(getSessionTokens()).toEqual({ accessToken: "new-access" });
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
    // `useAuth()` no longer exposes `logout` — the real flow is
    // `useLogoutMutation()` (D3/R3), exercised here the way `UserMenu` does.
    const cache = freshCache();
    setSessionTokens({ accessToken: "access" });
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchImpl);

    function LogoutProbe() {
      const logoutMutation = useLogoutMutation();
      return <button onClick={() => void logoutMutation.mutateAsync()}>logout</button>;
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
      const logoutMutation = useLogoutMutation();
      return (
        <button onClick={() => void logoutMutation.mutateAsync().catch(() => undefined)}>
          logout
        </button>
      );
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
    setSessionTokens({ accessToken: "a" });
    renderAuthWithCache(freshCache());
    const before = getSessionGeneration();

    act(() => notifySessionExpired());

    expect(getSessionGeneration()).not.toBe(before);
  });
});
