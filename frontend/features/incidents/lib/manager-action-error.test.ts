import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import type { IncidentStatus } from "../data";
import { managerActionMessage } from "./manager-action-error";

function apiError(status: number, code = "SOME_ERROR"): ApiError {
  return new ApiError({
    code,
    message: "a technical message that must never be rendered",
    status,
  });
}

describe("managerActionMessage (R2.5, R3.4, R6.1, D9)", () => {
  it("returns undefined when there is no error", () => {
    expect(managerActionMessage(null, "OPEN", "cancel")).toBeUndefined();
  });

  it("returns undefined for a non-ApiError", () => {
    expect(managerActionMessage(new Error("boom"), "OPEN", "cancel")).toBeUndefined();
  });

  it.each<[IncidentStatus, string]>([
    ["RESOLVED", "closed"],
    ["CANCELLED", "closed"],
    ["AWAITING_OWNER_APPROVAL", "awaiting-owner"],
    ["ASSIGNED", "out-of-order"],
    ["CLASSIFIED", "out-of-order"],
  ])("409 on a non-triage action over %s reads %s", (status, expected) => {
    expect(managerActionMessage(apiError(409), status, "cancel")).toBe(expected);
    expect(managerActionMessage(apiError(409), status, "assign")).toBe(expected);
  });

  it("409 on triage over a closed/awaiting-owner status keeps the generic reason", () => {
    expect(managerActionMessage(apiError(409), "RESOLVED", "triage")).toBe("closed");
    expect(managerActionMessage(apiError(409), "AWAITING_OWNER_APPROVAL", "triage")).toBe(
      "awaiting-owner",
    );
  });

  it("409 on triage over OPEN reads triage-not-classified, not the generic out-of-order (D9)", () => {
    expect(managerActionMessage(apiError(409), "OPEN", "triage")).toBe(
      "triage-not-classified",
    );
  });

  it("409 on triage over a non-OPEN out-of-order status keeps the generic reason", () => {
    expect(managerActionMessage(apiError(409), "ASSIGNED", "triage")).toBe("out-of-order");
  });

  it("422 on assign reads invalid-technician regardless of error.code (VALIDATION_ERROR shared on the wire)", () => {
    expect(
      managerActionMessage(apiError(422, "VALIDATION_ERROR"), "CLASSIFIED", "assign"),
    ).toBe("invalid-technician");
  });

  it("422 on triage reads invalid-cost regardless of error.code (VALIDATION_ERROR shared on the wire)", () => {
    expect(
      managerActionMessage(apiError(422, "VALIDATION_ERROR"), "OPEN", "triage"),
    ).toBe("invalid-cost");
  });

  it("422 on classify/cancel (no dedicated case) returns undefined", () => {
    expect(managerActionMessage(apiError(422), "OPEN", "classify")).toBeUndefined();
    expect(managerActionMessage(apiError(422), "OPEN", "cancel")).toBeUndefined();
  });

  it("403 is not handled here (section 5 hides the section instead)", () => {
    expect(managerActionMessage(apiError(403), "OPEN", "assign")).toBeUndefined();
  });

  it("never returns the technical error.message", () => {
    const error = apiError(409);
    const result = managerActionMessage(error, "ASSIGNED", "cancel");
    expect(result).not.toBe(error.message);
  });
});
