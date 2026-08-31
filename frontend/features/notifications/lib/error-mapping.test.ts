import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { NOTIFICATION_ERROR_KEYS, mapNotificationsError } from "./error-mapping";

function apiError(status: number, message: string): ApiError {
  return new ApiError({ code: "X", message, status });
}

describe("mapNotificationsError (R5.3)", () => {
  it("maps 404 to the not-found key", () => {
    expect(mapNotificationsError(apiError(404, "No such notification"))).toBe(
      NOTIFICATION_ERROR_KEYS.notFound,
    );
  });

  it("maps 403 to the forbidden key", () => {
    expect(mapNotificationsError(apiError(403, "nope"))).toBe(
      NOTIFICATION_ERROR_KEYS.forbidden,
    );
  });

  it("maps 401 to the session key, which the expiry flow owns", () => {
    expect(mapNotificationsError(apiError(401, "expired"))).toBe(
      NOTIFICATION_ERROR_KEYS.session,
    );
  });

  it("maps a 500 and a bare network error to the generic key", () => {
    expect(mapNotificationsError(apiError(500, "boom"))).toBe(
      NOTIFICATION_ERROR_KEYS.generic,
    );
    expect(mapNotificationsError(new TypeError("Failed to fetch"))).toBe(
      NOTIFICATION_ERROR_KEYS.generic,
    );
    expect(mapNotificationsError("not even an error")).toBe(
      NOTIFICATION_ERROR_KEYS.generic,
    );
  });

  it("never returns the server's own text — every outcome is an i18n key", () => {
    const cases = [
      apiError(404, "No such notification"),
      apiError(403, "Role is not allowed to perform this action"),
      apiError(500, "Unexpected notification error"),
      new Error("Unexpected notification error"),
    ];

    for (const error of cases) {
      const key = mapNotificationsError(error);
      expect(key.startsWith("notifications:errors.")).toBe(true);
      expect(Object.values(NOTIFICATION_ERROR_KEYS)).toContain(key);
    }
  });
});
