import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapReservationsError } from "./error-mapping";

function pending() {
  return { isPending: true, isError: false, error: null, data: undefined };
}

function success<T>(data: T) {
  return { isPending: false, isError: false, error: null, data };
}

function errored<TError>(error: TError) {
  return { isPending: false, isError: true, error, data: undefined };
}

describe("mapReservationsError (R5.4)", () => {
  it("a pending query maps to { kind: 'loading' }", () => {
    expect(mapReservationsError(pending())).toEqual({ kind: "loading" });
  });

  it("a result with data maps to { kind: 'ok', data } and preserves the type", () => {
    const data = { id: "r-1" };
    const result = mapReservationsError<{ id: string }>(success(data));
    expect(result).toEqual({ kind: "ok", data });
  });

  it("ApiError status 401 does not map to forbidden/not-found/validation/error — it stays in 'loading' (delegated to session)", () => {
    const err = new ApiError({
      code: "UNAUTHORIZED",
      message: "expired",
      status: 401,
    });
    const result = mapReservationsError(errored(err));
    expect(result.kind).toBe("loading");
  });

  it("ApiError status 403 maps to { kind: 'forbidden' }", () => {
    const err = new ApiError({
      code: "FORBIDDEN",
      message: "no permission",
      status: 403,
    });
    expect(mapReservationsError(errored(err))).toEqual({ kind: "forbidden" });
  });

  it("ApiError status 404 maps to { kind: 'not-found' }", () => {
    const err = new ApiError({
      code: "NOT_FOUND",
      message: "no such reservation",
      status: 404,
    });
    expect(mapReservationsError(errored(err))).toEqual({ kind: "not-found" });
  });

  it("ApiError status 422 with payload is mapped to { kind: 'validation' } and the payload is NOT in the variant", () => {
    const err = new ApiError({
      code: "validation_error",
      message: "cualquier cosa",
      details: { status: "invalid", property_id: "x" },
      status: 422,
    });
    const result = mapReservationsError(errored(err));
    expect(result).toEqual({ kind: "validation" });
    // The variant carries no message/details/code — strict equality above
    // already enforces it; the next line names the invariant for the reader.
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
    expect(mapReservationsError(errored(err))).toEqual({ kind: "error" });
  });

  it("a TypeError (network) maps to { kind: 'error' }", () => {
    expect(mapReservationsError(errored(new TypeError("network")))).toEqual({
      kind: "error",
    });
  });
});
