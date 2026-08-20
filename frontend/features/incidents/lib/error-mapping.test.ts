import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapIncidentsError } from "./error-mapping";

function makeErrorQueryResult(
  error: Error | null,
  data: unknown = undefined,
): Parameters<typeof mapIncidentsError>[0] {
  return {
    isPending: error === null && data === undefined,
    isError: error !== null,
    error,
    data,
  } as Parameters<typeof mapIncidentsError>[0];
}

describe("mapIncidentsError (R5.4)", () => {
  it("returns loading while pending", () => {
    expect(mapIncidentsError(makeErrorQueryResult(null))).toEqual({
      kind: "loading",
    });
  });

  it("treats 401 as delegated to session expiry — stays in loading", () => {
    const error = new ApiError({
      status: 401,
      code: "unauthorized",
      message: "token expired",
    });
    expect(mapIncidentsError(makeErrorQueryResult(error))).toEqual({
      kind: "loading",
    });
  });

  it("maps 403 to forbidden", () => {
    const error = new ApiError({ status: 403, code: "forbidden", message: "x" });
    expect(mapIncidentsError(makeErrorQueryResult(error))).toEqual({
      kind: "forbidden",
    });
  });

  it("maps 404 to not-found", () => {
    const error = new ApiError({ status: 404, code: "not_found", message: "x" });
    expect(mapIncidentsError(makeErrorQueryResult(error))).toEqual({
      kind: "not-found",
    });
  });

  it("maps 422 to validation WITHOUT exposing message / details / code", () => {
    const error = new ApiError({
      status: 422,
      code: "validation_error",
      message: "cualquier cosa",
      details: { status: "invalid" },
    });
    const state = mapIncidentsError<{ x: number }>(
      makeErrorQueryResult(error),
    );
    expect(state).toEqual({ kind: "validation" });
    expect(state).not.toHaveProperty("message");
    expect(state).not.toHaveProperty("details");
    expect(state).not.toHaveProperty("code");
  });

  it("maps 5xx to generic error", () => {
    const error = new ApiError({ status: 500, code: "internal", message: "x" });
    expect(mapIncidentsError(makeErrorQueryResult(error))).toEqual({
      kind: "error",
    });
  });

  it("maps TypeError (network) to generic error", () => {
    expect(
      mapIncidentsError(makeErrorQueryResult(new TypeError("network"))),
    ).toEqual({ kind: "error" });
  });

  it("returns ok with the data when the query resolves", () => {
    const data = { items: [], total: 0, page: 1, perPage: 20 };
    const state = mapIncidentsError<typeof data>(
      makeErrorQueryResult(null, data),
    );
    expect(state).toEqual({ kind: "ok", data });
  });
});