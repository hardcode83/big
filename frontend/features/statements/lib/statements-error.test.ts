import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { GENERIC_READ_ERROR_KEY, mapStatementDetailState, readErrorKey } from "./statements-error";

function apiError(status: number): ApiError {
  return new ApiError({ code: "X", message: "raw backend text", status });
}

describe("readErrorKey — distinguishes 403 from every other failure (R1.2, task 3.4)", () => {
  it("maps 403 to the forbidden key", () => {
    expect(readErrorKey(apiError(403))).toBe("statements:read.error.forbidden");
  });

  it("falls back to the generic key for other statuses", () => {
    expect(readErrorKey(apiError(500))).toBe(GENERIC_READ_ERROR_KEY);
    expect(readErrorKey(apiError(404))).toBe(GENERIC_READ_ERROR_KEY);
  });

  it("falls back to the generic key for a non-ApiError", () => {
    expect(readErrorKey(new Error("network down"))).toBe(GENERIC_READ_ERROR_KEY);
  });

  it("never surfaces the backend's raw message", () => {
    const key = readErrorKey(apiError(403));
    expect(key).not.toContain("raw backend text");
  });
});

describe("mapStatementDetailState — collapses 404 without revealing the cause (R1.2, R3.7, task 4.4)", () => {
  it("maps a pending query to loading", () => {
    expect(mapStatementDetailState({ isPending: true, isError: false, error: null, data: undefined })).toEqual({
      kind: "loading",
    });
  });

  it("maps 401 to loading, delegated to the shared session flow", () => {
    expect(
      mapStatementDetailState({ isPending: false, isError: true, error: apiError(401), data: undefined }),
    ).toEqual({ kind: "loading" });
  });

  it("maps 403 to forbidden", () => {
    expect(
      mapStatementDetailState({ isPending: false, isError: true, error: apiError(403), data: undefined }),
    ).toEqual({ kind: "forbidden" });
  });

  it("maps 404 to not-found the same way regardless of the underlying cause", () => {
    const unknownId = mapStatementDetailState({
      isPending: false,
      isError: true,
      error: apiError(404),
      data: undefined,
    });
    const otherTenant = mapStatementDetailState({
      isPending: false,
      isError: true,
      error: apiError(404),
      data: undefined,
    });
    expect(unknownId).toEqual({ kind: "not-found" });
    expect(otherTenant).toEqual({ kind: "not-found" });
  });

  it("maps every other failure (422, 5xx, network) to the generic error state", () => {
    expect(
      mapStatementDetailState({ isPending: false, isError: true, error: apiError(422), data: undefined }),
    ).toEqual({ kind: "error" });
    expect(
      mapStatementDetailState({ isPending: false, isError: true, error: apiError(500), data: undefined }),
    ).toEqual({ kind: "error" });
    expect(
      mapStatementDetailState({ isPending: false, isError: true, error: new Error("network"), data: undefined }),
    ).toEqual({ kind: "error" });
  });

  it("maps success to ok with the data", () => {
    const data = { id: "st-1" };
    expect(mapStatementDetailState({ isPending: false, isError: false, error: null, data })).toEqual({
      kind: "ok",
      data,
    });
  });
});
