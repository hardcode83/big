import { describe, expect, it } from "vitest";

import {
  MAX_INTERNAL_CODE,
  MAX_NAME,
  MAX_NOTES,
  MAX_WIFI_PASSWORD,
} from "./field-limits";
import {
  validatePropertyFields,
  type PropertyFieldValues,
} from "./field-validation";

function baseValues(
  overrides: Partial<PropertyFieldValues> = {},
): PropertyFieldValues {
  return {
    name: "Casa Azul",
    internal_code: "CASA-01",
    country: "ES",
    timezone: "Europe/Madrid",
    max_guests: 4,
    bedrooms: 2,
    bathrooms: 1,
    ...overrides,
  };
}

describe("validatePropertyFields (R1.3, design D5)", () => {
  it("returns no errors for fully valid values", () => {
    expect(validatePropertyFields(baseValues())).toEqual({});
  });

  it("flags an empty name as required", () => {
    expect(validatePropertyFields(baseValues({ name: "" }))).toEqual({
      name: "required",
    });
  });

  it("flags a whitespace-only name as required", () => {
    expect(validatePropertyFields(baseValues({ name: "   " }))).toEqual({
      name: "required",
    });
  });

  it("accepts a name at exactly MAX_NAME", () => {
    const name = "a".repeat(MAX_NAME);
    expect(validatePropertyFields(baseValues({ name }))).toEqual({});
  });

  it("flags a name one character past MAX_NAME as too long", () => {
    const name = "a".repeat(MAX_NAME + 1);
    expect(validatePropertyFields(baseValues({ name }))).toEqual({
      name: "tooLong",
    });
  });

  it("flags an empty internal_code as required", () => {
    expect(
      validatePropertyFields(baseValues({ internal_code: "" })),
    ).toEqual({ internal_code: "required" });
  });

  it("accepts an internal_code at exactly MAX_INTERNAL_CODE", () => {
    const internal_code = "a".repeat(MAX_INTERNAL_CODE);
    expect(validatePropertyFields(baseValues({ internal_code }))).toEqual(
      {},
    );
  });

  it("flags an internal_code one character past MAX_INTERNAL_CODE as too long", () => {
    const internal_code = "a".repeat(MAX_INTERNAL_CODE + 1);
    expect(validatePropertyFields(baseValues({ internal_code }))).toEqual({
      internal_code: "tooLong",
    });
  });

  it("flags an empty timezone as required (sdd-qa finding 1)", () => {
    expect(validatePropertyFields(baseValues({ timezone: "" }))).toEqual({
      timezone: "required",
    });
  });

  it("flags a whitespace-only timezone as required (sdd-qa finding 1)", () => {
    expect(validatePropertyFields(baseValues({ timezone: "   " }))).toEqual({
      timezone: "required",
    });
  });

  it("accepts a 2 uppercase letter country", () => {
    expect(validatePropertyFields(baseValues({ country: "FR" }))).toEqual(
      {},
    );
  });

  it("rejects a lowercase country", () => {
    expect(validatePropertyFields(baseValues({ country: "fr" }))).toEqual({
      country: "invalidCountry",
    });
  });

  it("rejects a 3-letter country", () => {
    expect(validatePropertyFields(baseValues({ country: "FRA" }))).toEqual({
      country: "invalidCountry",
    });
  });

  it("rejects an empty country", () => {
    expect(validatePropertyFields(baseValues({ country: "" }))).toEqual({
      country: "invalidCountry",
    });
  });

  it("accepts max_guests at the lower bound (1)", () => {
    expect(validatePropertyFields(baseValues({ max_guests: 1 }))).toEqual(
      {},
    );
  });

  it("rejects max_guests just below the lower bound (0)", () => {
    expect(validatePropertyFields(baseValues({ max_guests: 0 }))).toEqual({
      max_guests: "outOfRange",
    });
  });

  it("accepts max_guests at the upper bound (50)", () => {
    expect(validatePropertyFields(baseValues({ max_guests: 50 }))).toEqual(
      {},
    );
  });

  it("rejects max_guests just above the upper bound (51)", () => {
    expect(validatePropertyFields(baseValues({ max_guests: 51 }))).toEqual({
      max_guests: "outOfRange",
    });
  });

  it("accepts bedrooms at the lower bound (0)", () => {
    expect(validatePropertyFields(baseValues({ bedrooms: 0 }))).toEqual({});
  });

  it("rejects bedrooms just below the lower bound (-1)", () => {
    expect(validatePropertyFields(baseValues({ bedrooms: -1 }))).toEqual({
      bedrooms: "outOfRange",
    });
  });

  it("accepts bedrooms at the upper bound (50)", () => {
    expect(validatePropertyFields(baseValues({ bedrooms: 50 }))).toEqual(
      {},
    );
  });

  it("rejects bedrooms just above the upper bound (51)", () => {
    expect(validatePropertyFields(baseValues({ bedrooms: 51 }))).toEqual({
      bedrooms: "outOfRange",
    });
  });

  it("accepts bathrooms at the lower bound (0)", () => {
    expect(validatePropertyFields(baseValues({ bathrooms: 0 }))).toEqual(
      {},
    );
  });

  it("rejects bathrooms just below the lower bound (-1)", () => {
    expect(validatePropertyFields(baseValues({ bathrooms: -1 }))).toEqual({
      bathrooms: "outOfRange",
    });
  });

  it("accepts bathrooms at the upper bound (50)", () => {
    expect(validatePropertyFields(baseValues({ bathrooms: 50 }))).toEqual(
      {},
    );
  });

  it("rejects bathrooms just above the upper bound (51)", () => {
    expect(validatePropertyFields(baseValues({ bathrooms: 51 }))).toEqual({
      bathrooms: "outOfRange",
    });
  });

  it("accepts wifi_password at exactly MAX_WIFI_PASSWORD", () => {
    const wifi_password = "a".repeat(MAX_WIFI_PASSWORD);
    expect(
      validatePropertyFields(baseValues({ wifi_password })),
    ).toEqual({});
  });

  it("rejects wifi_password one character past MAX_WIFI_PASSWORD", () => {
    const wifi_password = "a".repeat(MAX_WIFI_PASSWORD + 1);
    expect(validatePropertyFields(baseValues({ wifi_password }))).toEqual({
      wifi_password: "tooLong",
    });
  });

  it("accepts a null wifi_password (unset)", () => {
    expect(
      validatePropertyFields(baseValues({ wifi_password: null })),
    ).toEqual({});
  });

  it("accepts each of the three notes at exactly MAX_NOTES", () => {
    const note = "a".repeat(MAX_NOTES);
    expect(
      validatePropertyFields(
        baseValues({
          access_notes: note,
          cleaning_notes: note,
          emergency_notes: note,
        }),
      ),
    ).toEqual({});
  });

  it("rejects each of the three notes one character past MAX_NOTES", () => {
    const note = "a".repeat(MAX_NOTES + 1);
    expect(
      validatePropertyFields(baseValues({ access_notes: note })),
    ).toEqual({ access_notes: "tooLong" });
    expect(
      validatePropertyFields(baseValues({ cleaning_notes: note })),
    ).toEqual({ cleaning_notes: "tooLong" });
    expect(
      validatePropertyFields(baseValues({ emergency_notes: note })),
    ).toEqual({ emergency_notes: "tooLong" });
  });

  it("accepts null notes fields (unset)", () => {
    expect(
      validatePropertyFields(
        baseValues({
          access_notes: null,
          cleaning_notes: null,
          emergency_notes: null,
        }),
      ),
    ).toEqual({});
  });

  it("collects multiple simultaneous errors", () => {
    expect(
      validatePropertyFields(
        baseValues({ name: "", country: "es", max_guests: 0 }),
      ),
    ).toEqual({
      name: "required",
      country: "invalidCountry",
      max_guests: "outOfRange",
    });
  });
});
