import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapPropertyFieldErrors } from "./field-errors";

describe("mapPropertyFieldErrors (R1.5, R2.7, design D6)", () => {
  it("keys a 422 validation envelope by loc's last segment", () => {
    const error = new ApiError({
      code: "VALIDATION_ERROR",
      message: "Invalid request",
      status: 422,
      details: {
        errors: [
          { loc: ["body", "name"], type: "value_error", msg: "name is required" },
          {
            loc: ["body", "country"],
            type: "value_error",
            msg: "must be 2 uppercase letters",
          },
        ],
      },
    });

    expect(mapPropertyFieldErrors(error)).toEqual({
      name: "name is required",
      country: "must be 2 uppercase letters",
    });
  });

  it("returns {} for a malformed 422 details body", () => {
    const error = new ApiError({
      code: "VALIDATION_ERROR",
      message: "bad",
      status: 422,
      details: { not_errors: [] },
    });
    expect(mapPropertyFieldErrors(error)).toEqual({});
  });

  // Backend message pinned verbatim from
  // backend/app/properties/infrastructure/repositories.py:551-558 — a wording
  // change there must fail this test loudly (design D6 risk mitigation).
  it("attributes a 409 duplicate internal_code to the internal_code field, pinning the exact backend message", () => {
    const error = new ApiError({
      code: "CONFLICT",
      message: "A property with that internal_code already exists for this tenant",
      status: 409,
    });

    expect(mapPropertyFieldErrors(error)).toEqual({
      internal_code:
        "A property with that internal_code already exists for this tenant",
    });
  });

  // Backend message pinned verbatim from
  // backend/app/properties/infrastructure/repositories.py:551-558.
  it("attributes a 409 duplicate pms_external_id to the pms_external_id field, pinning the exact backend message", () => {
    const error = new ApiError({
      code: "CONFLICT",
      message:
        "Another property of this tenant already claims that pms_external_id",
      status: 409,
    });

    expect(mapPropertyFieldErrors(error)).toEqual({
      pms_external_id:
        "Another property of this tenant already claims that pms_external_id",
    });
  });

  it("falls back to fallbackField for a 409 matching neither substring", () => {
    const error = new ApiError({
      code: "CONFLICT",
      message: "conflict",
      status: 409,
    });

    expect(mapPropertyFieldErrors(error, "name")).toEqual({
      name: "conflict",
    });
  });

  it("returns {} for a 409 matching neither substring and no fallbackField", () => {
    const error = new ApiError({
      code: "CONFLICT",
      message: "conflict",
      status: 409,
    });

    expect(mapPropertyFieldErrors(error)).toEqual({});
  });

  it("returns {} for anything else (403, 5xx, non-ApiError)", () => {
    expect(
      mapPropertyFieldErrors(
        new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
      ),
    ).toEqual({});
    expect(
      mapPropertyFieldErrors(
        new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
      ),
    ).toEqual({});
    expect(mapPropertyFieldErrors(new Error("network"))).toEqual({});
  });
});
