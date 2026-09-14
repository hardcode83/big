import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { GENERIC_READ_ERROR_KEY, readErrorKey } from "./statements-error";

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
