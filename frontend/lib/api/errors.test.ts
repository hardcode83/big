import { describe, expect, it } from "vitest";

import { isApiErrorEnvelope, parseApiError } from "@/lib/api/errors";

describe("isApiErrorEnvelope (PRD §23)", () => {
  it("accepts a well-formed envelope", () => {
    expect(
      isApiErrorEnvelope({ error: { code: "X", message: "y" } }),
    ).toBe(true);
  });

  it("rejects non-envelope shapes", () => {
    expect(isApiErrorEnvelope(null)).toBe(false);
    expect(isApiErrorEnvelope({})).toBe(false);
    expect(isApiErrorEnvelope({ error: {} })).toBe(false);
    expect(isApiErrorEnvelope({ error: { code: 1, message: "y" } })).toBe(false);
  });
});

describe("parseApiError", () => {
  it("preserves code, message and details from the envelope", async () => {
    const response = new Response(
      JSON.stringify({ error: { code: "C", message: "m", details: { a: 1 } } }),
      { status: 400 },
    );
    const error = await parseApiError(response);
    expect(error.code).toBe("C");
    expect(error.message).toBe("m");
    expect(error.details).toEqual({ a: 1 });
    expect(error.status).toBe(400);
  });

  it("produces a generic error when the body cannot be parsed", async () => {
    const response = new Response("not json", { status: 500 });
    const error = await parseApiError(response);
    expect(error.code).toBe("UNKNOWN_ERROR");
    expect(error.status).toBe(500);
  });
});
