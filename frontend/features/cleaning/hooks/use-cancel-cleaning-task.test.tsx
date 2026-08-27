import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { CleaningDataSource, CleaningTask } from "../data";
import { cleaningKeys } from "./query-keys";
import { useCancelCleaningTask } from "./use-cancel-cleaning-task";

const cancelTask = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getCleaningDataSource: (): CleaningDataSource =>
    ({
      listTasks: vi.fn(),
      listCleaners: vi.fn(),
      listProperties: vi.fn(),
      assignTask: vi.fn(),
      cancelTask,
    }) as unknown as CleaningDataSource,
}));

const task: CleaningTask = {
  id: "task-1",
  propertyId: "property-1",
  assignedCleanerId: null,
  status: "CANCELLED",
  scheduledStart: null,
  scheduledEnd: null,
  createdAt: "2026-08-19T18:00:00Z",
};

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const setQueryData = vi.spyOn(client, "setQueryData");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, invalidate, setQueryData, Wrapper };
}

beforeEach(() => {
  cancelTask.mockReset().mockResolvedValue(task);
});

describe("useCancelCleaningTask (R2.2, R3.1, R3.2, design D5)", () => {
  it("forwards the reason verbatim to the source", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useCancelCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", reason: "guest arrived early" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(cancelTask).toHaveBeenCalledWith(
      "tenant-1",
      "task-1",
      "guest arrived early",
    );
    expect(cancelTask).toHaveBeenCalledTimes(1);
  });

  it("invalidates the stalls prefix and the cleaning prefix on success (D5)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useCancelCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", reason: "guest arrived early" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const called = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(called).toEqual(
      expect.arrayContaining([
        ["tenant", "tenant-1", "blocked-transitions"],
        cleaningKeys.tasksPrefix("tenant-1"),
      ]),
    );
  });

  it("invalidates after a 409 too — a rejected cancellation must not stay on screen (R3.3)", async () => {
    cancelTask.mockRejectedValueOnce(
      new ApiError({
        code: "CLEANING_CANCEL_NOT_ALLOWED",
        message: "guest still in flat",
        status: 409,
      }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useCancelCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", reason: "guest arrived early" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const called = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(called).toEqual(
      expect.arrayContaining([
        ["tenant", "tenant-1", "blocked-transitions"],
        cleaningKeys.tasksPrefix("tenant-1"),
      ]),
    );
  });

  it("never retries a rejected write (R3.4)", async () => {
    cancelTask.mockRejectedValue(
      new ApiError({
        code: "CLEANING_CANCEL_NOT_ALLOWED",
        message: "guest still in flat",
        status: 409,
      }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useCancelCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", reason: "guest arrived early" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(cancelTask).toHaveBeenCalledTimes(1);
  });

  it("never writes the cache optimistically (D5)", async () => {
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useCancelCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", reason: "guest arrived early" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("does not invalidate another tenant's entries", async () => {
    const { client, Wrapper } = harness();
    const otherTenant = ["tenant", "tenant-2", "blocked-transitions", 1];
    client.setQueryData(otherTenant, {
      data: [],
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    });

    const { result } = renderHook(() => useCancelCleaningTask(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ taskId: "task-1", reason: "guest arrived early" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(otherTenant)?.isInvalidated).toBe(false);
  });
});