import { describe, expect, it } from "vitest";

import { buildReservationPatch, initialEditValues, validateEditValues } from "./edit-reservation-form";

const detail = {
  id: "r1", propertyId: "p1", status: "CONFIRMED", checkInDate: "2026-08-12", checkOutDate: "2026-08-15",
  nights: 3, totalGuests: 2, guestId: "g1", channel: "DIRECT", currency: "EUR", grossAmount: "100.00",
  paymentStatus: "PENDING", checkInTime: "15:00", checkOutTime: "11:00", adults: 2, children: 0,
  otaCommission: null, netAmount: null, cleaningRequired: true, accessStatus: "PENDING", externalChannelId: null,
  externalPmsId: null, internalNotes: "note", specialRequests: null, createdAt: "x", updatedAt: "x", guest: null,
} as never;

describe("reservation edit patch", () => {
  it("initializes from detail and sends only changed fields", () => {
    const values = initialEditValues(detail);
    values.checkOutDate = "2026-08-16";
    values.adults = "3";
    expect(buildReservationPatch(detail, values)).toEqual({ check_out_date: "2026-08-16", adults: 3 });
  });

  it("preserves explicit nullable clears and excludes guest/document fields", () => {
    const values = initialEditValues(detail);
    values.internalNotes = "";
    values.grossAmount = "";
    expect(buildReservationPatch(detail, values)).toEqual({ internal_notes: null, gross_amount: null });
    expect(JSON.stringify(buildReservationPatch(detail, values))).not.toMatch(/guest_id|document/);
  });

  it("rejects invalid intervals, non-integer counts, negative amounts, and non-finite values", () => {
    const values = initialEditValues(detail);
    values.checkInDate = "2026-08-20";
    values.checkOutDate = "2026-08-20";
    values.adults = "2.5";
    values.children = "-1";
    values.grossAmount = "NaN";
    values.netAmount = "Infinity";
    expect(validateEditValues(values)).toMatchObject({
      checkOutDate: "dateOrder",
      adults: "invalidAdults",
      children: "invalidGuests",
      grossAmount: "invalidAmount",
      netAmount: "invalidAmount",
    });
    expect(JSON.stringify(buildReservationPatch(detail, values))).not.toMatch(/NaN|Infinity/);
  });

  it("keeps contract-supported edit fields closed", () => {
    const values = initialEditValues(detail);
    const patch = buildReservationPatch(detail, values);
    expect(Object.keys(patch)).not.toEqual(expect.arrayContaining(["status", "payment_status", "cleaning_required", "channel", "guest_id"]));
  });
});
