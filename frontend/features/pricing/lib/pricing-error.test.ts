import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import {
  GENERIC_DECIDE_ERROR_KEY,
  GENERIC_GENERATE_ERROR_KEY,
  GENERIC_READ_ERROR_KEY,
  decideErrorKey,
  generateErrorKey,
  readErrorKey,
} from "./pricing-error";

function apiError(status: number): ApiError {
  return new ApiError({
    code: "SOMETHING_TECHNICAL",
    // Deliberately quotable-looking English, so a mapper that leaked the body
    // would be caught by the assertions below rather than look plausible.
    message: "Recommendation 7f3c is not in state RECOMMENDED",
    status,
    details: { field: "status", hint: "reload the page" },
  });
}

describe("decideErrorKey (R3.6, R3.7, R3.8)", () => {
  it("maps each status the PATCH can produce to its own key", () => {
    expect(decideErrorKey(apiError(403))).toBe("pricing:decide.error.forbidden");
    expect(decideErrorKey(apiError(404))).toBe("pricing:decide.error.notFound");
    expect(decideErrorKey(apiError(409))).toBe("pricing:decide.error.conflict");
    expect(decideErrorKey(apiError(422))).toBe("pricing:decide.error.invalid");
  });

  it("gives the 409 copy of its own, distinct from the generic one (R3.6)", () => {
    // The requirement is not just «handle 409» but «say something different».
    expect(decideErrorKey(apiError(409))).not.toBe(GENERIC_DECIDE_ERROR_KEY);
  });

  it("treats 403 as an error and never as success (R3.8)", () => {
    expect(decideErrorKey(apiError(403))).toBe("pricing:decide.error.forbidden");
  });

  it("falls back to the generic key for an unmapped status or a non-ApiError", () => {
    expect(decideErrorKey(apiError(500))).toBe(GENERIC_DECIDE_ERROR_KEY);
    expect(decideErrorKey(new Error("boom"))).toBe(GENERIC_DECIDE_ERROR_KEY);
    expect(decideErrorKey(undefined)).toBe(GENERIC_DECIDE_ERROR_KEY);
  });

  it("has no 401 branch — the HTTP client owns that path", () => {
    expect(decideErrorKey(apiError(401))).toBe(GENERIC_DECIDE_ERROR_KEY);
  });
});

describe("generateErrorKey (R3.7)", () => {
  it("maps only the statuses the generate call can produce", () => {
    expect(generateErrorKey(apiError(403))).toBe(
      "pricing:generate.error.forbidden",
    );
    expect(generateErrorKey(apiError(422))).toBe(
      "pricing:generate.error.invalid",
    );
  });

  it("has no 404 or 409 branch, because that path cannot produce them", () => {
    expect(generateErrorKey(apiError(404))).toBe(GENERIC_GENERATE_ERROR_KEY);
    expect(generateErrorKey(apiError(409))).toBe(GENERIC_GENERATE_ERROR_KEY);
  });
});

describe("readErrorKey (R3.8, design D17)", () => {
  it("distinguishes 403 from the generic read error", () => {
    // What a CLEANER arriving from the unfiltered sidebar sees. «Try again in a
    // few seconds» would be false: retrying never grants the permission.
    expect(readErrorKey(apiError(403))).toBe("pricing:read.error.forbidden");
    expect(readErrorKey(apiError(403))).not.toBe(GENERIC_READ_ERROR_KEY);
  });

  it("falls back to generic for everything else", () => {
    for (const status of [404, 409, 422, 500, 503]) {
      expect(readErrorKey(apiError(status))).toBe(GENERIC_READ_ERROR_KEY);
    }
  });
});

describe("none of the three mappers reads the backend body (R3.7)", () => {
  it("returns a key that contains nothing from message, code or details", () => {
    const error = apiError(409);
    const keys = [
      decideErrorKey(error),
      generateErrorKey(error),
      readErrorKey(error),
    ];
    for (const key of keys) {
      expect(key).not.toContain("Recommendation");
      expect(key).not.toContain("SOMETHING_TECHNICAL");
      expect(key).not.toContain("reload");
      // Every key is a static i18n address of the `pricing` namespace.
      expect(key).toMatch(/^pricing:[a-zA-Z.]+$/);
    }
  });

  it("is unaffected by the body: same status, different body, same key", () => {
    const withBody = new ApiError({
      code: "A",
      message: "one",
      status: 409,
      details: { x: 1 },
    });
    const withoutBody = new ApiError({ code: "B", message: "two", status: 409 });
    expect(decideErrorKey(withBody)).toBe(decideErrorKey(withoutBody));
  });
});
