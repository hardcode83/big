import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import esCleaning from "@/locales/es/cleaning.json";
import enCleaning from "@/locales/en/cleaning.json";

import { assignErrorKey, GENERIC_ASSIGN_ERROR_KEY } from "./assign-error";

function apiError(
  status: number,
  message = "Backend technical detail",
  code = "CODE",
) {
  return new ApiError({ code, message, status });
}

function resolve(
  key: string,
  catalog: typeof esCleaning | typeof enCleaning,
): unknown {
  return key
    .replace("cleaning:", "")
    .split(".")
    .reduce<unknown>(
      (acc, segment) =>
        acc && typeof acc === "object"
          ? (acc as Record<string, unknown>)[segment]
          : undefined,
      catalog,
    );
}

describe("assignErrorKey (R4.4, R4.5, R5.1, design D10)", () => {
  it("gives 403, 404, 409 and 422 four distinct keys", () => {
    const keys = [403, 404, 409, 422].map((status) =>
      assignErrorKey(apiError(status)),
    );
    expect(new Set(keys).size).toBe(4);
    expect(keys).not.toContain(GENERIC_ASSIGN_ERROR_KEY);
  });

  it.each([403, 404, 409, 422])(
    "resolves the key for %s in both locales",
    (status) => {
      const key = assignErrorKey(apiError(status));
      expect(typeof resolve(key, esCleaning)).toBe("string");
      expect(typeof resolve(key, enCleaning)).toBe("string");
    },
  );

  it.each([400, 401, 429, 500, 502, 503])(
    "falls back to the generic key for %s",
    (status) => {
      expect(assignErrorKey(apiError(status))).toBe(GENERIC_ASSIGN_ERROR_KEY);
    },
  );

  it("falls back to the generic key for anything that is not an ApiError", () => {
    expect(assignErrorKey(new Error("boom"))).toBe(GENERIC_ASSIGN_ERROR_KEY);
    expect(assignErrorKey(undefined)).toBe(GENERIC_ASSIGN_ERROR_KEY);
    expect(assignErrorKey(null)).toBe(GENERIC_ASSIGN_ERROR_KEY);
    expect(assignErrorKey("403")).toBe(GENERIC_ASSIGN_ERROR_KEY);
  });

  it("never returns the backend's message, not even as part of the key", () => {
    const secret = "SQLSTATE 23503 on cleaning_tasks.assigned_cleaner_id";
    for (const status of [403, 404, 409, 422, 500]) {
      const key = assignErrorKey(apiError(status, secret));
      expect(key).not.toContain(secret);
      expect(key.startsWith("cleaning:assign.error.")).toBe(true);
    }
  });

  it("resolves the generic key in both locales too", () => {
    expect(typeof resolve(GENERIC_ASSIGN_ERROR_KEY, esCleaning)).toBe("string");
    expect(typeof resolve(GENERIC_ASSIGN_ERROR_KEY, enCleaning)).toBe("string");
  });
});

describe("assignErrorKey refines the 409 by code (R2.1, R2.2, R2.3, design D7)", () => {
  it("gives the property-state conflict its own key, distinct from the task one", () => {
    const property = assignErrorKey(
      apiError(409, "blocked", "PROPERTY_STATE_CONFLICT"),
    );
    const task = assignErrorKey(apiError(409, "blocked", "CONFLICT"));

    expect(property).toBe("cleaning:assign.error.propertyState");
    expect(task).toBe("cleaning:assign.error.conflict");
    expect(property).not.toBe(task);
  });

  it("keeps the task message for CONFLICT — R2.2, no existing consumer moves", () => {
    expect(assignErrorKey(apiError(409, "x", "CONFLICT"))).toBe(
      "cleaning:assign.error.conflict",
    );
  });

  it("falls back to the task message for a 409 code it has never heard of", () => {
    // The deploy-skew window of design D7: a backend newer than this build can answer a
    // code that is not in the table. Degrading to the wording that shipped before is the
    // decision; throwing or showing nothing is not.
    expect(assignErrorKey(apiError(409, "x", "SOMETHING_INVENTED_LATER"))).toBe(
      "cleaning:assign.error.conflict",
    );
  });

  it.each([403, 404, 422])(
    "does not consult the code for %s — the refinement is scoped to 409",
    (status) => {
      const withPropertyCode = assignErrorKey(
        apiError(status, "x", "PROPERTY_STATE_CONFLICT"),
      );

      expect(withPropertyCode).toBe(assignErrorKey(apiError(status, "x", "CODE")));
      expect(withPropertyCode).not.toBe("cleaning:assign.error.propertyState");
    },
  );

  it("resolves the new key in both locales (R2.4)", () => {
    const key = assignErrorKey(apiError(409, "x", "PROPERTY_STATE_CONFLICT"));

    expect(typeof resolve(key, esCleaning)).toBe("string");
    expect(typeof resolve(key, enCleaning)).toBe("string");
  });

  it("still never returns the backend's message for the new cause", () => {
    const secret = "No policy entry for source state and trigger";
    const key = assignErrorKey(apiError(409, secret, "PROPERTY_STATE_CONFLICT"));

    expect(key).not.toContain(secret);
    expect(key).toBe("cleaning:assign.error.propertyState");
  });
});
