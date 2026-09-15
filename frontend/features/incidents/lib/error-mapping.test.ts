import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapIncidentsError } from "./error-mapping";

function pending() {
  return { isPending: true, isError: false, error: null, data: undefined };
}

function success<T>(data: T) {
  return { isPending: false, isError: false, error: null, data };
}

function errored<TError>(error: TError) {
  return { isPending: false, isError: true, error, data: undefined };
}

describe("mapIncidentsError (R5.4)", () => {
  it("a pending query maps to { kind: 'loading' }", () => {
    expect(mapIncidentsError(pending())).toEqual({ kind: "loading" });
  });

  it("a result with data maps to { kind: 'ok', data } and preserves the type", () => {
    const data = { items: [], total: 0, page: 1, perPage: 20 };
    const result = mapIncidentsError(success(data));
    expect(result).toEqual({ kind: "ok", data });
  });

  it("ApiError status 401 does NOT map to forbidden/not-found/validation/error — it stays in 'loading' (delegated to session)", () => {
    const err = new ApiError({
      code: "UNAUTHORIZED",
      message: "expired",
      status: 401,
    });
    expect(mapIncidentsError(errored(err)).kind).toBe("loading");
  });

  it("ApiError status 403 maps to { kind: 'forbidden' }", () => {
    const err = new ApiError({
      code: "FORBIDDEN",
      message: "no permission",
      status: 403,
    });
    expect(mapIncidentsError(errored(err))).toEqual({ kind: "forbidden" });
  });

  it("ApiError status 404 maps to { kind: 'not-found' }", () => {
    const err = new ApiError({
      code: "NOT_FOUND",
      message: "no such incident",
      status: 404,
    });
    expect(mapIncidentsError(errored(err))).toEqual({ kind: "not-found" });
  });

  it("ApiError status 422 with payload maps to { kind: 'validation' } and the payload is NOT in the variant", () => {
    const err = new ApiError({
      code: "validation_error",
      message: "cualquier cosa",
      details: { status: "invalid" },
      status: 422,
    });
    const result = mapIncidentsError(errored(err));
    expect(result).toEqual({ kind: "validation" });
    expect(result).not.toHaveProperty("message");
    expect(result).not.toHaveProperty("details");
    expect(result).not.toHaveProperty("code");
  });

  it("ApiError status 500 maps to { kind: 'error' }", () => {
    const err = new ApiError({
      code: "SERVER",
      message: "boom",
      status: 500,
    });
    expect(mapIncidentsError(errored(err))).toEqual({ kind: "error" });
  });

  it("a TypeError (network) maps to { kind: 'error' }", () => {
    expect(mapIncidentsError(errored(new TypeError("network")))).toEqual({
      kind: "error",
    });
  });

  /**
   * R2.1/R4.3 (task 3.4): a 404 on the incident staff-thread read must map to
   * `not-found`, the same "task/incident not available" branch every other
   * read uses. Unlike `mapCleanerError`, `mapIncidentsError` has no `kind`
   * discriminator parameter — it is generic over the *status code* alone, so
   * "messages" needs no dedicated branch: the existing 404 rule already
   * covers it (see Implementation Notes, section 3).
   */
  it("a 404 on the messages read maps to not-found — the generic rule, no dedicated 'messages' branch needed", () => {
    const err = new ApiError({
      code: "NOT_FOUND",
      message: "no such incident",
      status: 404,
    });
    expect(mapIncidentsError(errored(err))).toEqual({ kind: "not-found" });
  });

  /**
   * R2.2/R2.3 (task 3.4): a 422 on the send-message mutation maps to
   * `validation` — same generic rule. `mapIncidentsError`'s input type (`Pick<
   * UseQueryResult, "isPending" | "isError" | "error" | "data">`) is
   * structurally satisfied by `UseMutationResult` too (both expose the same
   * four fields in TanStack Query v5), so the mutation hook can reuse this
   * mapper unchanged — no dedicated "sendMessage" branch needed either.
   */
  it("a 422 on the send-message mutation maps to validation — mapIncidentsError works for a mutation result shape too", () => {
    const err = new ApiError({
      code: "validation_error",
      message: "content too long",
      status: 422,
    });
    expect(mapIncidentsError(errored(err))).toEqual({ kind: "validation" });
  });
});