import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { CleaningTask } from "../data/dto";
import { mapCleaningDetailError, type CleaningDetailState } from "./detail-error";

const TASK: CleaningTask = {
  id: "task-1",
  propertyId: "property-1",
  reservationId: "reservation-1",
  assignedCleanerId: "cleaner-9",
  status: "ASSIGNED",
  scheduledStart: "2026-09-20T10:00:00Z",
  scheduledEnd: "2026-09-20T12:00:00Z",
  createdAt: "2026-09-19T18:00:00Z",
  completedAt: null,
  validationStatus: "PENDING",
  validatedAt: null,
};

function pending() {
  return { isPending: true, isError: false, error: null, data: undefined };
}

function success(data: CleaningTask) {
  return { isPending: false, isError: false, error: null, data };
}

function errored(error: Error) {
  return { isPending: false, isError: true, error, data: undefined };
}

function apiError(status: number, code = "CODE") {
  return new ApiError({ code, message: `backend says ${status}`, status });
}

describe("mapCleaningDetailError (R1.2, R1.4, design D5/D12)", () => {
  it("a pending query maps to { kind: 'loading' }", () => {
    expect(mapCleaningDetailError(pending(), vi.fn())).toEqual({
      kind: "loading",
    });
  });

  it("a successful query maps to { kind: 'success', data } preserving the DTO type", () => {
    const result = mapCleaningDetailError(success(TASK), vi.fn());
    expect(result).toEqual({ kind: "success", data: TASK });
    if (result.kind === "success") {
      expect(result.data).toBe(TASK);
    }
  });

  it("ApiError status 403 maps to { kind: 'forbidden' } (D5 row 1)", () => {
    expect(mapCleaningDetailError(errored(apiError(403)), vi.fn())).toEqual({
      kind: "forbidden",
    });
  });

  it("ApiError status 404 maps to { kind: 'not-found' } (D5 row 2, D12)", () => {
    expect(
      mapCleaningDetailError(errored(apiError(404, "NOT_FOUND")), vi.fn()),
    ).toEqual({ kind: "not-found" });
  });

  it("forbidden and not-found do not overlap — they are discriminated kinds, distinct objects", () => {
    const forbidden: CleaningDetailState = mapCleaningDetailError(
      errored(apiError(403)),
      vi.fn(),
    );
    const notFound: CleaningDetailState = mapCleaningDetailError(
      errored(apiError(404)),
      vi.fn(),
    );

    expect(forbidden.kind).toBe("forbidden");
    expect(notFound.kind).toBe("not-found");
    expect(forbidden).not.toEqual(notFound);
    expect(forbidden).not.toHaveProperty("data");
    expect(notFound).not.toHaveProperty("data");
  });

  it("ApiError status 422 maps to { kind: 'validation' } (D5 row 3)", () => {
    expect(mapCleaningDetailError(errored(apiError(422)), vi.fn())).toEqual({
      kind: "validation",
    });
  });

  it.each([400, 500, 502, 503])(
    "ApiError status %s maps to { kind: 'error', refetch } (D5 row 4)",
    (status) => {
      const refetch = vi.fn();
      const result = mapCleaningDetailError(errored(apiError(status)), refetch);
      expect(result.kind).toBe("error");
      if (result.kind === "error") {
        expect(result.refetch).toBe(refetch);
      }
    },
  );

  it("a TypeError (network failure) maps to { kind: 'error', refetch }", () => {
    const refetch = vi.fn();
    const result = mapCleaningDetailError(
      errored(new TypeError("network down")),
      refetch,
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.refetch).toBe(refetch);
    }
  });

  it("a non-ApiError unknown error maps to { kind: 'error', refetch }", () => {
    const refetch = vi.fn();
    const result = mapCleaningDetailError(
      errored(new Error("anything")),
      refetch,
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.refetch).toBe(refetch);
    }
  });

  it("the { kind: 'error' } variant's refetch actually re-triggers the query (R1.4)", () => {
    const refetch = vi.fn();
    const result = mapCleaningDetailError(errored(apiError(500)), refetch);
    if (result.kind !== "error") {
      throw new Error("expected error kind");
    }
    result.refetch();
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("never leaks the backend's error.message — not as a key, not as a field", () => {
    const secret = "SQLSTATE 23503 on cleaning_tasks.assigned_cleaner_id";
    const result = mapCleaningDetailError(
      errored(new ApiError({ code: "x", message: secret, status: 500 })),
      vi.fn(),
    );
    const serialised = JSON.stringify(result);
    expect(serialised).not.toContain(secret);
  });

  it("the discriminated union is exhaustive — no fallback kind escapes", () => {
    const refetch = vi.fn();
    const samples = [
      pending(),
      success(TASK),
      errored(apiError(403)),
      errored(apiError(404)),
      errored(apiError(422)),
      errored(apiError(500)),
      errored(new TypeError("net")),
      errored(new Error("x")),
    ];
    for (const sample of samples) {
      const result = mapCleaningDetailError(sample, refetch);
      expect([
        "loading",
        "success",
        "forbidden",
        "not-found",
        "validation",
        "error",
      ]).toContain(result.kind);
    }
  });
});
