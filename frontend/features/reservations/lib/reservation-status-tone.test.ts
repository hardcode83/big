import { describe, expect, it } from "vitest";

import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";

import type { ReservationStatus } from "../data/dto";
import {
  RESERVATION_STATUS_TONE,
  reservationStatusTone,
} from "./reservation-status-tone";

describe("RESERVATION_STATUS_TONE (R2 AC3)", () => {
  it("covers exactly the 7 values of the generated ReservationStatus union", () => {
    expect(Object.keys(RESERVATION_STATUS_TONE).sort()).toEqual(
      [
        "PENDING",
        "CONFIRMED",
        "CANCELLED",
        "CHECKED_IN_ESTIMATED",
        "CHECKED_OUT_ESTIMATED",
        "COMPLETED",
        "NO_SHOW",
      ].sort(),
    );
  });

  it("only uses tones the shared palette actually defines", () => {
    // The tone is an index into `TONE_BADGE_CLASS`; a typo would render a
    // badge with no classes rather than fail.
    for (const status of Object.keys(
      RESERVATION_STATUS_TONE,
    ) as ReservationStatus[]) {
      expect(TONE_BADGE_CLASS).toHaveProperty(
        RESERVATION_STATUS_TONE[status],
      );
    }
  });
});

describe("reservationStatusTone", () => {
  it("returns the mapped tone for each known status", () => {
    for (const status of Object.keys(
      RESERVATION_STATUS_TONE,
    ) as ReservationStatus[]) {
      expect(reservationStatusTone(status)).toBe(
        RESERVATION_STATUS_TONE[status],
      );
    }
  });

  it("falls back to grey for a status the contract does not declare", () => {
    // Deploy skew: an eighth status arrives before the frontend is rebuilt.
    const unknown = "SUPERSEDED" as ReservationStatus;
    expect(reservationStatusTone(unknown)).toBe("gray");
  });

  it("falls back to grey for an inherited key, not to a function", () => {
    // `STATUS_TONE["toString"]` is a function, which `?? "gray"` would not
    // catch. The status crosses the API boundary with no runtime validation.
    for (const key of ["toString", "constructor", "valueOf", "__proto__"]) {
      expect(reservationStatusTone(key as ReservationStatus)).toBe("gray");
    }
  });
});
