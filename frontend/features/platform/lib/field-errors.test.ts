import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapFieldErrors } from "./field-errors";

describe("mapFieldErrors (R3.3, R4.5, design D5)", () => {
  it("keys a 422 validation envelope by loc's last segment", () => {
    const error = new ApiError({
      code: "VALIDATION_ERROR",
      message: "Invalid request",
      status: 422,
      details: {
        errors: [
          { loc: ["body", "name"], type: "value_error", msg: "name is required" },
          {
            loc: ["body", "billing_email"],
            type: "value_error",
            msg: "not a valid email",
          },
        ],
      },
    });

    expect(mapFieldErrors(error)).toEqual({
      name: "name is required",
      billing_email: "not a valid email",
    });
  });

  it("attributes a 409 to the given fallbackField", () => {
    const error = new ApiError({
      code: "CONFLICT",
      message: "A tenant named 'MAGNO' already exists",
      status: 409,
    });

    expect(mapFieldErrors(error, "name")).toEqual({
      name: "A tenant named 'MAGNO' already exists",
    });
  });

  it("returns {} for a 409 with no fallbackField", () => {
    const error = new ApiError({ code: "CONFLICT", message: "conflict", status: 409 });

    expect(mapFieldErrors(error)).toEqual({});
  });

  it("returns {} for anything else (403, 5xx, non-ApiError, malformed 422 details)", () => {
    expect(
      mapFieldErrors(new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 })),
    ).toEqual({});
    expect(
      mapFieldErrors(
        new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
      ),
    ).toEqual({});
    expect(mapFieldErrors(new Error("network"))).toEqual({});
    expect(
      mapFieldErrors(
        new ApiError({
          code: "VALIDATION_ERROR",
          message: "bad",
          status: 422,
          details: { not_errors: [] },
        }),
      ),
    ).toEqual({});
  });
});
