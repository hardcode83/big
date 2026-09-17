import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { CleaningDataSource, CleaningTask } from "../data";
import { cleaningKeys } from "./query-keys";
import { useCleaningTask } from "./use-cleaning-task";

const listTasks = vi.hoisted(() => vi.fn());
const listCleaners = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const assignTask = vi.hoisted(() => vi.fn());
const cancelTask = vi.hoisted(() => vi.fn());
const createTask = vi.hoisted(() => vi.fn());
const validateTask = vi.hoisted(() => vi.fn());
const getTask = vi.hoisted(() => vi.fn());

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
    cancelTask,
    createTask,
    validateTask,
    getTask,
  }),
}));

const task: CleaningTask = {
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

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

beforeEach(() => {
  getTask.mockReset().mockResolvedValue(task);
  listTasks.mockReset();
  listCleaners.mockReset();
  listProperties.mockReset();
  assignTask.mockReset();
  cancelTask.mockReset();
  createTask.mockReset();
  validateTask.mockReset();
});

describe("useCleaningTask (R1.1, R1.3, R1.4, design D3/D5/D12)", () => {
  it("starts in loading state and never calls the source until enabled", () => {
    const { result } = renderHook(() => useCleaningTask(undefined), {
      wrapper: wrapper(),
    });

    expect(result.current.isPending).toBe(true);
    expect(getTask).not.toHaveBeenCalled();
  });

  it("stays pending (never fires) when taskId is empty — enabled: false", () => {
    const { result } = renderHook(() => useCleaningTask(""), {
      wrapper: wrapper(),
    });

    expect(result.current.isPending).toBe(true);
    expect(result.current.fetchStatus).toBe("idle");
    expect(getTask).not.toHaveBeenCalled();
  });

  it("asks the source for the task id from the session tenant", async () => {
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getTask).toHaveBeenCalledWith("tenant-1", "task-1");
    expect(getTask).toHaveBeenCalledTimes(1);
  });

  it("keys the query on ['tenant', tenantId, 'cleaning-task', taskId] (design D4)", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    }

    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [storedKey] = client
      .getQueryCache()
      .findAll()
      .map((q) => q.queryKey);
    expect(storedKey).toEqual(cleaningKeys.task("tenant-1", "task-1"));
  });

  it("surfaces success with the mapped task", async () => {
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(task);
  });

  it("surfaces a 403 as an error with status 403 (D5 forbidden branch)", async () => {
    getTask.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(403);
  });

  it("surfaces a 404 as an error with status 404 (D5 not-found branch, D12)", async () => {
    getTask.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
    );
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(404);
  });

  it("surfaces a 422 as an error with status 422 (D5 validation branch)", async () => {
    getTask.mockRejectedValue(
      new ApiError({ code: "VALIDATION", message: "bad uuid", status: 422 }),
    );
    const { result } = renderHook(() => useCleaningTask("not-a-uuid"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(422);
  });

  it("surfaces any other status as a generic error (D5 error branch)", async () => {
    getTask.mockRejectedValue(
      new ApiError({ code: "INTERNAL", message: "boom", status: 500 }),
    );
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(500);
  });

  it("never retries — a rejected read stays rejected (D3, retry: false)", async () => {
    getTask.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
    );
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(getTask).toHaveBeenCalledTimes(1);
  });

  it("never retries a successful read either", async () => {
    const { result } = renderHook(() => useCleaningTask("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getTask).toHaveBeenCalledTimes(1);
  });
});