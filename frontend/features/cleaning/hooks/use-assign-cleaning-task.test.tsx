import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { CleaningDataSource, CleaningTask } from "../data";
import { cleaningKeys } from "./query-keys";
import { useAssignCleaningTask } from "./use-assign-cleaning-task";

const listTasks = vi.hoisted(() => vi.fn());
const listCleaners = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const assignTask = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getCleaningDataSource: (): CleaningDataSource => ({
    listTasks,
    listCleaners,
    listProperties,
    assignTask,
  }),
}));

const task: CleaningTask = {
  id: "task-1",
  propertyId: "property-1",
  assignedCleanerId: "cleaner-9",
  status: "ASSIGNED",
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
  assignTask.mockReset().mockResolvedValue(task);
  listTasks.mockReset();
  listCleaners.mockReset();
  listProperties.mockReset();
});

describe("useAssignCleaningTask (R4.1, R4.5, R4.6, design D9)", () => {
  it("asks the source for exactly the task and the cleaner, nothing else", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(assignTask).toHaveBeenCalledWith("tenant-1", "task-1", "cleaner-9");
    expect(assignTask).toHaveBeenCalledTimes(1);
  });

  it("invalidates the whole task prefix on success (design D9)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: cleaningKeys.tasksPrefix("tenant-1"),
    });
  });

  it.each([403, 404, 409, 422] as const)(
    "invalidates the task prefix after a %s too, so a rejected assignment cannot stay on screen (R4.4, R4.5)",
    async (status) => {
      assignTask.mockRejectedValue(
        new ApiError({ code: "CODE", message: "no", status }),
      );
      const { invalidate, Wrapper } = harness();
      const { result } = renderHook(() => useAssignCleaningTask(), {
        wrapper: Wrapper,
      });

      result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(invalidate).toHaveBeenCalledWith({
        queryKey: cleaningKeys.tasksPrefix("tenant-1"),
      });
    },
  );

  it("never retries a rejected write", async () => {
    assignTask.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "no", status: 409 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(assignTask).toHaveBeenCalledTimes(1);
  });

  it("never writes the cache optimistically (design D9)", async () => {
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("leaves no filter/page combination holding stale data", async () => {
    const { client, Wrapper } = harness();
    const combinations = [
      cleaningKeys.tasks("tenant-1", {}, 1),
      cleaningKeys.tasks("tenant-1", {}, 2),
      cleaningKeys.tasks("tenant-1", { status: "CREATED" }, 1),
      cleaningKeys.tasks("tenant-1", { propertyId: "property-1" }, 3),
    ];
    for (const key of combinations) {
      client.setQueryData(key, { data: [], total: 0, page: 1, per_page: 20, total_pages: 0 });
    }

    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    for (const key of combinations) {
      expect(
        client.getQueryState(key)?.isInvalidated,
        JSON.stringify(key),
      ).toBe(true);
    }
  });

  it("does not invalidate another tenant's entries", async () => {
    const { client, Wrapper } = harness();
    const otherTenant = cleaningKeys.tasks("tenant-2", {}, 1);
    client.setQueryData(otherTenant, {
      data: [],
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    });

    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(otherTenant)?.isInvalidated).toBe(false);
  });

  it("does not invalidate the catalogs, which the assignment cannot have changed", async () => {
    const { client, Wrapper } = harness();
    const catalogs = [
      cleaningKeys.cleaners("tenant-1"),
      cleaningKeys.properties("tenant-1"),
    ];
    for (const key of catalogs) {
      client.setQueryData(key, []);
    }

    const { result } = renderHook(() => useAssignCleaningTask(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ taskId: "task-1", cleanerId: "cleaner-9" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    for (const key of catalogs) {
      expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(
        false,
      );
    }
  });
});
