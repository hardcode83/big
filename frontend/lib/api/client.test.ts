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

  it("resolves typed path parameters and omits undefined query parameters", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ data: [] }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    await client.request("/api/v1/timeline/{property_id}", {
      pathParams: { property_id: "property/1" },
      query: {
        event_type: "INCIDENT_CREATED",
        severity: undefined,
        page: 1,
      },
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api/api/v1/timeline/property%2F1?event_type=INCIDENT_CREATED&page=1",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("serializes a boolean query parameter as true/false", async () => {
    // `active` on `GET /api/v1/pricing-rules` is the first `boolean` query
    // parameter in the tree (`pricing-web` design D20). The assertion is on the
    // wire format FastAPI parses, not just on the type compiling.
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    await client.request("/api/v1/pricing-rules", {
      query: { page: 1, active: true },
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api/api/v1/pricing-rules?page=1&active=true",
      expect.objectContaining({ method: "GET" }),
    );
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

  it("does not invoke recovery for an unauthenticated 401", async () => {
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

    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("recovers one eligible authenticated request and retries it once", async () => {
    const onUnauthorized = vi.fn().mockResolvedValue(true);
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "UNAUTHENTICATED", message: "expired" } },
          { status: 401 },
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      getHeaders: () => ({ Authorization: "Bearer access" }),
      onUnauthorized,
    });

    await expect(client.request("/health")).resolves.toEqual({ ok: true });
    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(onUnauthorized).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/health",
        hadAccessToken: true,
        retryCount: 0,
      }),
    );
  });

  it.each([
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
  ] as const)("excludes %s from automatic recovery", async (path) => {
    const onUnauthorized = vi.fn().mockResolvedValue(true);
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "UNAUTHENTICATED", message: "expired" } },
        { status: 401 },
      ),
    );
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      getHeaders: () => ({ Authorization: "Bearer access" }),
      onUnauthorized,
    });

    await client
      .request(path, { method: "POST", body: path.endsWith("login") ? { email: "a", password: "b" } : path.endsWith("refresh") ? { refresh_token: "refresh" } : undefined } as never)
      .catch(() => undefined);

    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("does not retry the original request twice", async () => {
    const onUnauthorized = vi.fn().mockResolvedValue(true);
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "UNAUTHENTICATED", message: "still expired" } },
        { status: 401 },
      ),
    );
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      getHeaders: () => ({ Authorization: "Bearer access" }),
      onUnauthorized,
    });

    await client.request("/health").catch(() => undefined);

    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
  it("sends a FormData body without a Content-Type of its own (D2)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, { status: 201 }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });
    const formData = new FormData();
    formData.append("stage", "BEFORE");
    formData.append("file", new Blob(["bytes"], { type: "image/jpeg" }), "a.jpg");

    await client.request("/api/v1/incidents/{incident_id}/photos", {
      method: "POST",
      pathParams: { incident_id: "inc-1" },
      formData,
    });

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(formData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });

  it("does not JSON.stringify a multipart request and still sends Authorization", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, { status: 201 }));
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      getHeaders: () => ({ Authorization: "Bearer access" }),
    });
    const formData = new FormData();
    formData.append("stage", "AFTER");

    await client.request("/api/v1/incidents/{incident_id}/photos", {
      method: "POST",
      pathParams: { incident_id: "inc-1" },
      formData,
    });

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(typeof init.body).not.toBe("string");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer access");
  });

  it("replays the same FormData instance on the retry after a recovered 401", async () => {
    const onUnauthorized = vi.fn().mockResolvedValue(true);
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "UNAUTHENTICATED", message: "expired" } },
          { status: 401 },
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ id: "photo-1" }, { status: 201 }));
    const client = createApiClient({
      baseUrl: "https://api",
      fetchImpl,
      getHeaders: () => ({ Authorization: "Bearer access" }),
      onUnauthorized,
    });
    const formData = new FormData();
    formData.append("stage", "BEFORE");

    await client.request("/api/v1/incidents/{incident_id}/photos", {
      method: "POST",
      pathParams: { incident_id: "inc-1" },
      formData,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const retryInit = fetchImpl.mock.calls[1][1] as RequestInit;
    expect(retryInit.body).toBe(formData);
    expect(new Headers(retryInit.headers).has("Content-Type")).toBe(false);
  });

  it("leaves an existing JSON request untouched (no regression from D2)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, { status: 200 }));
    const client = createApiClient({ baseUrl: "https://api", fetchImpl });

    await client.request("/api/v1/incidents/{incident_id}/resolve", {
      method: "POST",
      pathParams: { incident_id: "inc-1" },
      body: { final_cost: "120.50" },
    });

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(JSON.stringify({ final_cost: "120.50" }));
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });
});
