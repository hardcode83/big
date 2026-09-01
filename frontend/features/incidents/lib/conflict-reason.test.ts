import { describe, expect, it } from "vitest";

import type { IncidentStatus } from "../data";
import { conflictReason } from "./conflict-reason";

describe("conflictReason (D7)", () => {
  it.each<[IncidentStatus, string]>([
    ["OPEN", "out-of-order"],
    ["CLASSIFIED", "out-of-order"],
    ["AWAITING_OWNER_APPROVAL", "awaiting-owner"],
    ["ASSIGNED", "out-of-order"],
    ["ACCEPTED", "out-of-order"],
    ["IN_PROGRESS", "out-of-order"],
    ["WAITING_EXTERNAL_PARTS", "out-of-order"],
    ["RESOLVED", "closed"],
    ["CANCELLED", "closed"],
  ])("reads %s as %s", (status, expected) => {
    expect(conflictReason(status)).toBe(expected);
  });

  it("puts closed ahead of awaiting-owner, as the domain does", () => {
    // `_refuse_if_closed_or_awaiting_owner` asks about closed first. The two
    // conditions never overlap in a single status, so what this pins is the
    // reading order rather than a live ambiguity — which is what keeps the
    // client's explanation in step with the server's refusal.
    expect(conflictReason("RESOLVED")).toBe("closed");
    expect(conflictReason("AWAITING_OWNER_APPROVAL")).toBe("awaiting-owner");
  });
});
