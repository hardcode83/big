import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import {
  GENERIC_ERROR_KEY,
  errorMessageKey,
  isConflict,
  isForbidden,
  isNotFound,
} from "./errors";

function apiError(status: number): ApiError {
  return new ApiError({
    code: "CONFLICT",
    message: "Conversation is already escalated",
    status,
  });
}

describe("errorMessageKey maps status to a key (task 2.5, D18)", () => {
  it.each([
    [403, "errors.forbidden"],
    [404, "errors.notFound"],
    [409, "errors.conflict"],
    [422, "errors.invalid"],
  ])("maps %i to %s", (status, key) => {
    expect(errorMessageKey(apiError(status))).toBe(key);
  });

  it("falls back to a generic key for any other status", () => {
    expect(errorMessageKey(apiError(500))).toBe(GENERIC_ERROR_KEY);
    expect(errorMessageKey(apiError(418))).toBe(GENERIC_ERROR_KEY);
  });

  it("falls back to the generic key for a non-ApiError failure", () => {
    expect(errorMessageKey(new Error("network down"))).toBe(GENERIC_ERROR_KEY);
    expect(errorMessageKey(undefined)).toBe(GENERIC_ERROR_KEY);
  });

  it("never returns the technical message as visible copy (R1.4)", () => {
    const error = apiError(409);
    const key = errorMessageKey(error);
    expect(key).not.toContain(error.message);
    expect(key).not.toContain("already escalated");
    expect(key).not.toContain(error.code);
    expect(key).toMatch(/^errors\.[a-zA-Z]+$/);
  });
});

describe("dedicated-screen predicates (task 2.5, D17)", () => {
  it("recognizes 403, 404 and 409 and nothing else", () => {
    expect(isForbidden(apiError(403))).toBe(true);
    expect(isForbidden(apiError(404))).toBe(false);
    expect(isNotFound(apiError(404))).toBe(true);
    expect(isNotFound(apiError(403))).toBe(false);
    expect(isConflict(apiError(409))).toBe(true);
    expect(isConflict(apiError(422))).toBe(false);
  });

  it("treats a non-ApiError failure as none of them", () => {
    for (const predicate of [isForbidden, isNotFound, isConflict]) {
      expect(predicate(new Error("network down"))).toBe(false);
      expect(predicate(null)).toBe(false);
    }
  });
});
