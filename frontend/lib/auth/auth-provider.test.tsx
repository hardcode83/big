import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/lib/auth";
import {
  clearSessionTokens,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";
import { RuntimeConfigProvider } from "@/lib/config/runtime-config-provider";
import { fireEvent, render, screen } from "@/test/render";

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
      }}
    >
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </RuntimeConfigProvider>,
  );
}

describe("AuthProvider", () => {
  afterEach(() => {
    clearSessionTokens();
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
  });

  it("logs out locally even when the backend logout is unavailable", async () => {
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

    render(
      <RuntimeConfigProvider
        config={{
          apiBaseUrl: "",
          appEnv: "test",
          defaultLocale: "es",
          featureFlags: {},
          appVersion: "",
          buildCommitShort: "",
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
    expect(fetchImpl).toHaveBeenCalledOnce();
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
