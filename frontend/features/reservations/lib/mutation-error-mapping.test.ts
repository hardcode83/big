import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { reservationMutationErrorKey } from "./mutation-error-mapping";

describe("reservationMutationErrorKey (D5)", () => {
  it.each([
    [401, "reservations:mutation.errors.session"],
    [403, "reservations:mutation.errors.forbidden"],
    [404, "reservations:mutation.errors.notFound"],
    [409, "reservations:mutation.errors.conflict"],
    [422, "reservations:mutation.errors.validation"],
  ] as const)("maps ApiError %s to a localizable key", (status, expected) => {
    expect(
      reservationMutationErrorKey(
        new ApiError({
          code: "PRIVATE_CODE",
          message: "PII secret message",
          details: { email: "guest@example.com" },
          status,
        }),
      ),
    ).toBe(expected);
  });

  it("maps 5xx and network errors without exposing server data", () => {
    expect(
      reservationMutationErrorKey(
        new ApiError({ code: "INTERNAL", message: "trace PII", status: 503 }),
      ),
    ).toBe("reservations:mutation.errors.server");
    expect(reservationMutationErrorKey(new TypeError("network PII"))).toBe(
      "reservations:mutation.errors.network",
    );
  });
});
