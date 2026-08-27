import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `server-only` is aliased to a no-op stub in `vitest.config.ts` so the module
// can be unit-tested in jsdom.

const cookieStoreValue = vi.hoisted(() => ({ value: "autohostai.session.present=1" }));
const cookiesMock = vi.hoisted(() =>
  vi.fn(async () => ({
    toString: () => cookieStoreValue.value,
  })),
);

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
}));

import { serverFetch } from "./server-client";

const originalFetch = global.fetch;

describe("serverFetch (R4)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    process.env.BACKEND_INTERNAL_URL = "http://backend.test";
    cookieStoreValue.value = "autohostai.session.present=1";
  });

  afterEach(() => {
    global.fetch = originalFetch;
    delete process.env.BACKEND_INTERNAL_URL;
  });

  it("throws when BACKEND_INTERNAL_URL is not configured", async () => {
    delete process.env.BACKEND_INTERNAL_URL;

    await expect(serverFetch("/api/v1/auth/me")).rejects.toThrow(
      "serverFetch: BACKEND_INTERNAL_URL is not configured",
    );
  });

  it("forwards the inbound cookies by default", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: "user-1", role: "CLEANER" }),
    });

    await serverFetch("/api/v1/auth/me");

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init.headers);
    expect(headers.get("Cookie")).toBe("autohostai.session.present=1");
    expect(headers.get("Content-Type")).toBeNull();
  });

  it("does NOT forward cookies when forwardCookies: false", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({}),
    });

    await serverFetch("/api/v1/auth/me", { forwardCookies: false });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init.headers);
    expect(headers.get("Cookie")).toBeNull();
  });

  it("applies the default 2 s timeout", async () => {
    // A fetch that returns immediately. We verify the AbortSignal is created —
    // testing the actual timeout fires would slow the suite and bring flake
    // risk; the AbortSignal API contract is what we rely on.
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({}),
    });

    await serverFetch("/api/v1/auth/me");

    const [, passedInit] = fetchMock.mock.calls[0];
    expect(passedInit.signal).toBeDefined();
    expect(passedInit.signal).toBeInstanceOf(AbortSignal);
  });

  it("returns the parsed JSON body on 2xx", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: "user-1", role: "CLEANER" }),
    });

    const body = await serverFetch("/api/v1/auth/me");

    expect(body).toEqual({ id: "user-1", role: "CLEANER" });
  });

  it("returns undefined on 204", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      json: async () => {
        throw new Error("should not parse on 204");
      },
    });

    const body = await serverFetch("/api/v1/auth/logout", {
      method: "POST",
    });

    expect(body).toBeUndefined();
  });

  it("throws ApiError on non-2xx", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({
        error: { code: "UNAUTHORIZED", message: "no token", details: {} },
      }),
    });

    await expect(serverFetch("/api/v1/auth/me")).rejects.toMatchObject({
      status: 401,
      code: "UNAUTHORIZED",
    });
  });

  it("sends Content-Type: application/json when body is present", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({}),
    });

    await serverFetch("/api/v1/auth/login", {
      method: "POST",
      body: { email: "u@example.com", password: "x" },
    });

    const [, init] = fetchMock.mock.calls[0];
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ email: "u@example.com", password: "x" }));
  });
});