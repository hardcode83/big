import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import {
  CANCEL_ERROR_TABLE,
  CREATE_ERROR_TABLE,
  GENERIC_CANCEL_ERROR_KEY,
  GENERIC_CREATE_ERROR_KEY,
  GENERIC_VALIDATE_ERROR_KEY,
  keyForStatus,
  VALIDATE_ERROR_TABLE,
} from "./manage-error";

function apiError(
  status: number,
  code = "CODE",
  message = "Backend technical detail",
) {
  return new ApiError({ code, message, status });
}

describe("keyForStatus — create table (R1.4, design D8)", () => {
  it.each([
    [403, "cleaning:create.error.forbidden"],
    [404, "cleaning:create.error.notFound"],
    [409, "cleaning:create.error.ambiguousTemplate"],
    [422, "cleaning:create.error.invalid"],
  ])("maps status %s to %s", (status, expected) => {
    expect(
      keyForStatus(apiError(status as number), CREATE_ERROR_TABLE, GENERIC_CREATE_ERROR_KEY),
    ).toBe(expected);
  });

  it("gives all four statuses distinct keys, none generic", () => {
    const keys = [403, 404, 409, 422].map((status) =>
      keyForStatus(apiError(status), CREATE_ERROR_TABLE, GENERIC_CREATE_ERROR_KEY),
    );
    expect(new Set(keys).size).toBe(4);
    expect(keys).not.toContain(GENERIC_CREATE_ERROR_KEY);
  });

  it.each([400, 401, 429, 500, 502, 503])(
    "falls back to the generic key for %s",
    (status) => {
      expect(
        keyForStatus(apiError(status), CREATE_ERROR_TABLE, GENERIC_CREATE_ERROR_KEY),
      ).toBe(GENERIC_CREATE_ERROR_KEY);
    },
  );

  it("does not refine the 409 by code — create has a single 409 cause", () => {
    const a = keyForStatus(
      apiError(409, "CONFLICT"),
      CREATE_ERROR_TABLE,
      GENERIC_CREATE_ERROR_KEY,
    );
    const b = keyForStatus(
      apiError(409, "SOMETHING_ELSE"),
      CREATE_ERROR_TABLE,
      GENERIC_CREATE_ERROR_KEY,
    );
    expect(a).toBe("cleaning:create.error.ambiguousTemplate");
    expect(b).toBe("cleaning:create.error.ambiguousTemplate");
  });
});

describe("keyForStatus — validate table (R3.5, design D8)", () => {
  it.each([
    [403, "cleaning:validate.error.forbidden"],
    [404, "cleaning:validate.error.notFound"],
    [409, "cleaning:validate.error.notCompleted"],
  ])("maps status %s to %s", (status, expected) => {
    expect(
      keyForStatus(apiError(status as number), VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY),
    ).toBe(expected);
  });

  it("gives all three statuses distinct keys, none generic", () => {
    const keys = [403, 404, 409].map((status) =>
      keyForStatus(apiError(status), VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY),
    );
    expect(new Set(keys).size).toBe(3);
    expect(keys).not.toContain(GENERIC_VALIDATE_ERROR_KEY);
  });

  it.each([400, 401, 422, 429, 500])(
    "falls back to the generic key for %s",
    (status) => {
      expect(
        keyForStatus(apiError(status), VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY),
      ).toBe(GENERIC_VALIDATE_ERROR_KEY);
    },
  );

  it("does not refine the 409 by code — validate has a single 409 cause", () => {
    const a = keyForStatus(
      apiError(409, "CONFLICT"),
      VALIDATE_ERROR_TABLE,
      GENERIC_VALIDATE_ERROR_KEY,
    );
    const b = keyForStatus(
      apiError(409, "PROPERTY_STATE_CONFLICT"),
      VALIDATE_ERROR_TABLE,
      GENERIC_VALIDATE_ERROR_KEY,
    );
    expect(a).toBe("cleaning:validate.error.notCompleted");
    expect(b).toBe("cleaning:validate.error.notCompleted");
  });
});

describe("keyForStatus — cancel table, refined by code within 409 (R4.5, design D8)", () => {
  it.each([
    [403, "cleaning:cancel.error.forbidden"],
    [404, "cleaning:cancel.error.notFound"],
  ])("maps status %s to %s", (status, expected) => {
    expect(
      keyForStatus(apiError(status as number), CANCEL_ERROR_TABLE, GENERIC_CANCEL_ERROR_KEY),
    ).toBe(expected);
  });

  it("gives the terminal-task 409 (CONFLICT) its own key", () => {
    expect(
      keyForStatus(apiError(409, "CONFLICT"), CANCEL_ERROR_TABLE, GENERIC_CANCEL_ERROR_KEY),
    ).toBe("cleaning:cancel.error.terminal");
  });

  it("gives the property-state 409 (PROPERTY_STATE_CONFLICT) a distinct key", () => {
    const propertyState = keyForStatus(
      apiError(409, "PROPERTY_STATE_CONFLICT"),
      CANCEL_ERROR_TABLE,
      GENERIC_CANCEL_ERROR_KEY,
    );
    const terminal = keyForStatus(
      apiError(409, "CONFLICT"),
      CANCEL_ERROR_TABLE,
      GENERIC_CANCEL_ERROR_KEY,
    );
    expect(propertyState).toBe("cleaning:cancel.error.propertyState");
    expect(propertyState).not.toBe(terminal);
  });

  it("falls back to the terminal-task key for a 409 code it has never heard of", () => {
    expect(
      keyForStatus(
        apiError(409, "SOMETHING_INVENTED_LATER"),
        CANCEL_ERROR_TABLE,
        GENERIC_CANCEL_ERROR_KEY,
      ),
    ).toBe("cleaning:cancel.error.terminal");
  });

  it.each([403, 404])(
    "does not consult the code for %s — the refinement is scoped to 409",
    (status) => {
      const withPropertyCode = keyForStatus(
        apiError(status, "PROPERTY_STATE_CONFLICT"),
        CANCEL_ERROR_TABLE,
        GENERIC_CANCEL_ERROR_KEY,
      );
      const withOtherCode = keyForStatus(
        apiError(status, "CODE"),
        CANCEL_ERROR_TABLE,
        GENERIC_CANCEL_ERROR_KEY,
      );
      expect(withPropertyCode).toBe(withOtherCode);
      expect(withPropertyCode).not.toBe("cleaning:cancel.error.propertyState");
    },
  );

  it.each([400, 401, 422, 429, 500])(
    "falls back to the generic key for %s",
    (status) => {
      expect(
        keyForStatus(apiError(status), CANCEL_ERROR_TABLE, GENERIC_CANCEL_ERROR_KEY),
      ).toBe(GENERIC_CANCEL_ERROR_KEY);
    },
  );
});

describe("keyForStatus — errors that are not an ApiError", () => {
  it("falls back to the generic key for each table", () => {
    expect(keyForStatus(new Error("boom"), CREATE_ERROR_TABLE, GENERIC_CREATE_ERROR_KEY)).toBe(
      GENERIC_CREATE_ERROR_KEY,
    );
    expect(keyForStatus(undefined, VALIDATE_ERROR_TABLE, GENERIC_VALIDATE_ERROR_KEY)).toBe(
      GENERIC_VALIDATE_ERROR_KEY,
    );
    expect(keyForStatus(null, CANCEL_ERROR_TABLE, GENERIC_CANCEL_ERROR_KEY)).toBe(
      GENERIC_CANCEL_ERROR_KEY,
    );
  });
});

describe("keyForStatus never leaks ApiError.message (R1.4, R3.5, R4.5)", () => {
  it("never returns the backend's message, not even as part of the key", () => {
    const secret = "SQLSTATE 23503 on cleaning_tasks.checklist_template_id";
    for (const status of [403, 404, 409, 422, 500]) {
      const key = keyForStatus(
        apiError(status, "CODE", secret),
        CREATE_ERROR_TABLE,
        GENERIC_CREATE_ERROR_KEY,
      );
      expect(key).not.toContain(secret);
    }
  });
});
