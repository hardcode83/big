import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import {
  createErrorKey,
  GENERIC_CREATE_ERROR_KEY,
  GENERIC_READ_ERROR_KEY,
  GENERIC_RESPOND_ERROR_KEY,
  readErrorKey,
  respondErrorKey,
} from "./reviews-error";

/**
 * Pins D10: the choice is made by HTTP status, never by `ApiError.message`,
 * `code` or `details`. Tests construct `ApiError` with arbitrary bodies to make
 * sure those fields never leak into the key.
 *
 * Also pins the three reachable-code tables:
 *
 *   - respond/edit: 403, 404, 409, 422, generic
 *   - create:       403, 422, generic (no 404 — invalid property is a 422)
 *   - read:         403, 404, generic (no 409, no 422)
 */

function apiError(status: number, message = "tech msg", code = "tech"): ApiError {
  return new ApiError({
    status,
    message,
    code,
    details: { detail: "should not leak" },
  });
}

describe("respondErrorKey", () => {
  it("403 → forbidden key", () => {
    expect(respondErrorKey(apiError(403))).not.toBe(GENERIC_RESPOND_ERROR_KEY);
    expect(respondErrorKey(apiError(403))).toContain("forbidden");
  });
  it("404 → notFound key", () => {
    expect(respondErrorKey(apiError(404))).toContain("notFound");
  });
  it("409 → conflict key (R3.5)", () => {
    expect(respondErrorKey(apiError(409))).toContain("conflict");
    expect(respondErrorKey(apiError(409))).not.toBe(GENERIC_RESPOND_ERROR_KEY);
  });
  it("422 → invalid key", () => {
    expect(respondErrorKey(apiError(422))).toContain("invalid");
  });
  it("falls through to generic for unreached statuses (e.g. 500)", () => {
    expect(respondErrorKey(apiError(500))).toBe(GENERIC_RESPOND_ERROR_KEY);
  });
  it("falls through to generic for non-ApiError inputs", () => {
    expect(respondErrorKey(new Error("anything"))).toBe(GENERIC_RESPOND_ERROR_KEY);
    expect(respondErrorKey({ status: 409 })).toBe(GENERIC_RESPOND_ERROR_KEY);
  });
  it("does not leak message/code/details into the key", () => {
    const e = apiError(409, "another action was taken first", "INVALID_STATE", {
      state: "POSTED_MANUALLY",
    });
    const key = respondErrorKey(e);
    expect(key).not.toContain("another");
    expect(key).not.toContain("INVALID_STATE");
    expect(key).not.toContain("POSTED_MANUALLY");
  });
});

describe("createErrorKey", () => {
  it("403 → forbidden key", () => {
    expect(createErrorKey(apiError(403))).toContain("forbidden");
  });
  it("422 → invalid key", () => {
    expect(createErrorKey(apiError(422))).toContain("invalid");
  });
  it("does NOT distinguish 404 (invalid property is a 422)", () => {
    expect(createErrorKey(apiError(404))).toBe(GENERIC_CREATE_ERROR_KEY);
  });
  it("falls through to generic for 500", () => {
    expect(createErrorKey(apiError(500))).toBe(GENERIC_CREATE_ERROR_KEY);
  });
});

describe("readErrorKey", () => {
  it("403 → forbidden key", () => {
    expect(readErrorKey(apiError(403))).toContain("forbidden");
  });
  it("404 → notFound key", () => {
    expect(readErrorKey(apiError(404))).toContain("notFound");
  });
  it("does NOT distinguish 409 or 422 on read", () => {
    expect(readErrorKey(apiError(409))).toBe(GENERIC_READ_ERROR_KEY);
    expect(readErrorKey(apiError(422))).toBe(GENERIC_READ_ERROR_KEY);
  });
});