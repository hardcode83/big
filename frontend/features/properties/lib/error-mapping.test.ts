import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapPropertiesError } from "./error-mapping";

function errored(error: Error) {
  return { isPending: false, isError: true as const, error, data: undefined };
}

/** `ApiError` takes the PRD §23 envelope, not positional arguments. */
function apiError(status: number, message = "boom"): ApiError {
  return new ApiError({ code: "TEST_ERROR", message, status });
}

const PAGE = { data: [], page: 1, perPage: 20, total: 0, totalPages: 0 };

describe("mapPropertiesError (R3)", () => {
  it("reports loading while the request is in flight (R3.1)", () => {
    expect(
      mapPropertiesError({
        isPending: true,
        isError: false,
        error: null,
        data: undefined,
      }),
    ).toEqual({ kind: "loading" });
  });

  it("passes the data through on success", () => {
    expect(
      mapPropertiesError({
        isPending: false,
        isError: false,
        error: null,
        data: PAGE,
      }),
    ).toEqual({ kind: "ok", data: PAGE });
  });

  it("maps 403 to a distinct forbidden state (R3.2)", () => {
    expect(mapPropertiesError(errored(apiError(403, "forbidden")))).toEqual({
      kind: "forbidden",
    });
  });

  it("maps 422 to validation without exposing the server envelope (R3.3)", () => {
    const state = mapPropertiesError(
      errored(apiError(422, "Unprocessable: field xyz is invalid")),
    );
    expect(state).toEqual({ kind: "validation" });
    // The variant carries no payload at all, so no server text can reach the UI.
    expect(JSON.stringify(state)).not.toContain("xyz");
  });

  it("maps 401 to loading, not to an error state (R3.4)", () => {
    // The decision this pins: the auth provider owns the refresh + redirect, so
    // surfacing an error here would flash a misleading state on every token
    // rotation. A regression that returned `error` or `forbidden` for 401 would
    // be a visible flicker for something working as designed.
    expect(mapPropertiesError(errored(apiError(401, "unauthorized")))).toEqual({
      kind: "loading",
    });
  });

  it("maps 404 on this list endpoint to the generic error, not to not-found (R3.5)", () => {
    // A collection does not "not exist": the endpoint answers with an empty
    // page when the tenant has no properties. So a 404 means something
    // genuinely unexpected (proxy rewrite, wrong base path) and must offer the
    // retry, not a reassuring "nothing found" screen.
    expect(mapPropertiesError(errored(apiError(404, "not found")))).toEqual({
      kind: "error",
    });
  });

  it("maps 5xx to the generic error", () => {
    expect(mapPropertiesError(errored(apiError(500)))).toEqual({
      kind: "error",
    });
  });

  it("maps a network failure to the generic error", () => {
    expect(mapPropertiesError(errored(new TypeError("Failed to fetch")))).toEqual(
      { kind: "error" },
    );
  });

  it("never produces not-found for this feature (design D8)", () => {
    // Exhaustive over every status this mapper branches on, plus a network
    // error: none of them may yield `not-found`, which is unreachable here.
    const statuses = [401, 403, 404, 409, 422, 429, 500, 503];
    for (const status of statuses) {
      const state = mapPropertiesError(errored(apiError(status)));
      expect(state.kind).not.toBe("not-found");
    }
    expect(
      mapPropertiesError(errored(new TypeError("Failed to fetch"))).kind,
    ).not.toBe("not-found");
  });
});
