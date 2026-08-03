import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("createApiClient (D12)", () => {
  it("restricts paths to their declared OpenAPI methods", () => {
    const client = createApiClient({ baseUrl: "https://api" });

    if (false) {
      // @ts-expect-error POST is not declared for /health.
      client.request("/health", { method: "POST" });
      // @ts-expect-error A POST-only route requires its declared method.
      client.request("/api/v1/auth/login");
      client.request("/api/v1/auth/login", {
        method: "POST",
        body: { email: "user@example.com", password: "x" },
      });
    }
  });

  it("joins base URL and path and returns the typed health response", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
    const client = createApiClient({
      baseUrl: "https://api.example.com/",
      fetchImpl,
    });

    const result = await client.request("/health");

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.example.com/health",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toEqual({ ok: 1 });
  });

  it("serializes a JSON body and sets Content-Type", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, { status: 201 }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    await client.request("/api/v1/auth/login", {
      method: "POST",
      body: { email: "user@example.com", password: "x" },
    });

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(
      JSON.stringify({ email: "user@example.com", password: "x" }),
    );
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json",
    );
  });

  it("contributes headers from getHeaders (auth extension point)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      getHeaders: () => ({ Authorization: "Bearer future-token" }),
    });

    await client.request("/health");

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer future-token",
    );
  });

  it("returns undefined for a 204 No Content response", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    expect(
      await client.request("/api/v1/auth/logout", { method: "POST" }),
    ).toBeUndefined();
  });

  it("maps a PRD §23 error envelope to ApiError", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "VALIDATION_ERROR",
            message: "Invalid payload",
            details: { field: "name" },
          },
        },
        { status: 422 },
      ),
    );
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    await expect(client.request("/health")).rejects.toMatchObject({
      code: "VALIDATION_ERROR",
      message: "Invalid payload",
      status: 422,
      details: { field: "name" },
    });
  });

  it("falls back to a generic ApiError when the body is not an envelope", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response("<html>502</html>", { status: 502 }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    const error = (await client.request("/health").catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("UNKNOWN_ERROR");
    expect(error.status).toBe(502);
  });

  it("invokes onUnauthorized on a 401 (refresh extension point)", async () => {
    const onUnauthorized = vi.fn();
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "UNAUTHENTICATED", message: "no" } },
        { status: 401 },
      ),
    );
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      onUnauthorized,
    });

    await client.request("/health").catch(() => undefined);

    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
