import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { stallsErrorKey } from "./stalls-error";

const GENERIC = "card.blocked.cancelCleaning.dialog.error.generic";

function apiError(status: number, code = "ERROR"): ApiError {
  return new ApiError({ code, message: "technical detail", status });
}

describe("stallsErrorKey (R3.3, R3.4)", () => {
  it("maps 409 to the conflict copy — the case R3.4 names", () => {
    expect(stallsErrorKey(apiError(409), GENERIC)).toBe(
      "card.blocked.error.conflict",
    );
  });

  it("maps 403 to the forbidden copy, not to «try again»", () => {
    expect(stallsErrorKey(apiError(403), GENERIC)).toBe(
      "card.blocked.error.forbidden",
    );
  });

  it.each([400, 404, 422, 500, 502, 503])(
    "falls back to the caller's generic key on %i",
    (status) => {
      expect(stallsErrorKey(apiError(status), GENERIC)).toBe(GENERIC);
    },
  );

  it("does not branch on 401 — the client's refresh owns that path", () => {
    expect(stallsErrorKey(apiError(401), GENERIC)).toBe(GENERIC);
  });

  it("falls back to the generic key for a non-ApiError rejection", () => {
    expect(stallsErrorKey(new Error("network down"), GENERIC)).toBe(GENERIC);
    expect(stallsErrorKey(undefined, GENERIC)).toBe(GENERIC);
    expect(stallsErrorKey(null, GENERIC)).toBe(GENERIC);
  });

  it("never returns the backend's technical message", () => {
    const key = stallsErrorKey(apiError(409, "GUEST_ALREADY_CHECKED_IN"), GENERIC);
    expect(key).not.toContain("technical detail");
    expect(key.startsWith("card.blocked.")).toBe(true);
  });

  it("honours a different generic key per action", () => {
    const resolveGeneric = "card.blocked.resolveIncident.dialog.error.generic";
    expect(stallsErrorKey(apiError(500), resolveGeneric)).toBe(resolveGeneric);
  });
});
