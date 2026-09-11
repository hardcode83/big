import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { reservationMutationErrorKey } from "./mutation-error-mapping";

describe("reservationMutationErrorKey (D5)", () => {
  it.each([
    [401, "session"], [403, "forbidden"], [404, "notFound"], [409, "conflict"], [422, "validation"],
  ] as const)("maps ApiError %s to a localizable key", (status, expected) => {
    expect(
      reservationMutationErrorKey(
        new ApiError({
          code: "PRIVATE_CODE",
          message: "PII secret message",
          details: { email: "guest@example.com" },
          status,
        }),
        "edit",
      ),
    ).toBe(`reservations:mutation.errors.edit.${expected}`);
  });

  it("maps 5xx and network errors without exposing server data", () => {
    expect(
      reservationMutationErrorKey(
        new ApiError({ code: "INTERNAL", message: "trace PII", status: 503 }),
        "cancel",
      ),
    ).toBe("reservations:mutation.errors.cancel.server");
    expect(reservationMutationErrorKey(new TypeError("network PII"), "cancel")).toBe("reservations:mutation.errors.cancel.network");
  });
});
