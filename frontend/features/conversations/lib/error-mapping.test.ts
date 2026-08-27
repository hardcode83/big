import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { mapConversationsError } from "./error-mapping";

/**
 * Direct unit tests for the conversations error mapper (R3.7, R6.4).
 *
 * The component tests exercise the mapper transitively; these pin the
 * mapping itself so a future refactor that drops a status branch or
 * exposes the backend envelope fails red instead of silently regressing
 * the user's experience of a `404` vs a `403` vs a `5xx`.
 */
describe("mapConversationsError (R3.7, R6.4)", () => {
  describe("loading", () => {
    it("returns `loading` while the query is pending", () => {
      expect(
        mapConversationsError({ isPending: true, isError: false, error: null, data: undefined }),
      ).toEqual({ kind: "loading" });
    });

    it("returns `loading` on a 401 — the session-expiry flow owns the redirect", () => {
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new ApiError({
            code: "UNAUTHENTICATED",
            message: "session expired",
            status: 401,
          }),
          data: undefined,
        }),
      ).toEqual({ kind: "loading" });
    });
  });

  describe("forbidden", () => {
    it("returns `forbidden` on a 403", () => {
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
          data: undefined,
        }),
      ).toEqual({ kind: "forbidden" });
    });
  });

  describe("not-found", () => {
    it("returns `not-found` on a 404", () => {
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new ApiError({ code: "NOT_FOUND", message: "missing", status: 404 }),
          data: undefined,
        }),
      ).toEqual({ kind: "not-found" });
    });
  });

  describe("validation", () => {
    it("returns `validation` on a 422 without reading the envelope", () => {
      // The mapper must NOT expose `message` / `details` / `code` of the
      // backend envelope (R6.4): the UI shows only localized copy.
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new ApiError({
            code: "VALIDATION_ERROR",
            message: "field content exceeds 4000 chars",
            status: 422,
            details: { field: "content", max: 4000 },
          }),
          data: undefined,
        }),
      ).toEqual({ kind: "validation" });
    });
  });

  describe("generic error", () => {
    it("returns `error` on a 5xx (server-side failure)", () => {
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new ApiError({ code: "INTERNAL", message: "boom", status: 500 }),
          data: undefined,
        }),
      ).toEqual({ kind: "error" });
    });

    it("returns `error` on a network `TypeError` (no response at all)", () => {
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new TypeError("Failed to fetch"),
          data: undefined,
        }),
      ).toEqual({ kind: "error" });
    });

    it("returns `error` on any non-ApiError (defensive)", () => {
      expect(
        mapConversationsError({
          isPending: false,
          isError: true,
          error: new Error("something broke"),
          data: undefined,
        }),
      ).toEqual({ kind: "error" });
    });
  });

  describe("ok", () => {
    it("returns `ok` with the data when the query resolved successfully", () => {
      const data = { id: "c1", status: "OPEN" };
      const result = mapConversationsError({
        isPending: false,
        isError: false,
        error: null,
        data,
      });
      expect(result).toEqual({ kind: "ok", data });
    });

    it("preserves the generic TData type at the call site", () => {
      // Compile-time check: the generic parameter survives. If a future
      // change drops the generic, this assignment fails to typecheck.
      const typedResult = mapConversationsError<{ id: string }>({
        isPending: false,
        isError: false,
        error: null,
        data: { id: "x" },
      });
      if (typedResult.kind === "ok") {
        expect(typedResult.data.id).toBe("x");
      } else {
        throw new Error("expected ok");
      }
    });
  });
});
