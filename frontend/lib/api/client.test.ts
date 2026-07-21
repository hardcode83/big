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
  it("joins base URL and path and returns parsed JSON as unknown", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
    const client = createApiClient({
      baseUrl: "https://api.example.com/",
      fetchImpl,
    });

    const result = await client.request("/things");

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.example.com/things",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toEqual({ ok: 1 });
  });

  it("serializes a JSON body and sets Content-Type", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, { status: 201 }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    await client.request("/things", { method: "POST", body: { name: "x" } });

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(JSON.stringify({ name: "x" }));
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

    await client.request("/things");

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

    expect(await client.request("/things", { method: "DELETE" })).toBeUndefined();
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

    await expect(client.request("/things")).rejects.toMatchObject({
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

    const error = (await client.request("/things").catch((e) => e)) as ApiError;
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

    await client.request("/things").catch(() => undefined);

    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
