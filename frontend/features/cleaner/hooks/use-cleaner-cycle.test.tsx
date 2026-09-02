import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { cleanerKeys } from "./query-keys";
import {
  useCleanerTaskCycleAction,
  useCompleteCleaningTask,
  useRejectCleaningTask,
  useUploadCleaningPhoto,
} from "./use-cleaner-cycle";

const TENANT = "tenant-from-session";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

const acceptMock = vi.fn();
const rejectMock = vi.fn();
const startMock = vi.fn();
const completeMock = vi.fn();
const completeChecklistItemMock = vi.fn();
const uploadPhotoMock = vi.fn();
const reportIncidentMock = vi.fn();

vi.spyOn(dataModule, "getCleanerDataSource").mockImplementation(
  () =>
    ({
      acceptTask: acceptMock,
      rejectTask: rejectMock,
      startTask: startMock,
      completeTask: completeMock,
      completeChecklistItem: completeChecklistItemMock,
      uploadPhoto: uploadPhotoMock,
      reportIncident: reportIncidentMock,
    }) as unknown as ReturnType<typeof dataModule.getCleanerDataSource>,
);

const TASK = { id: "task-1", status: "ACCEPTED" } as never;
const ACK = {
  id: "incident-1",
  status: "OPEN",
  createdAt: "2026-08-20T10:00:00Z",
} as never;
const PHOTO = {
  id: "photo-1",
  cleaningTaskId: "task-1",
  photoType: "kitchen",
} as never;
const ITEM = {
  itemId: "kitchen",
  label: "Cocina",
  required: true,
  completed: true,
  completedAt: "2026-08-20T10:00:00Z",
  completedBy: "cleaner-1",
} as never;

function trackedClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidated: unknown[][] = [];
  const removed: unknown[][] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters) => {
    invalidated.push([...((filters?.queryKey ?? []) as unknown[])]);
    return Promise.resolve();
  });
  vi.spyOn(client, "removeQueries").mockImplementation((filters) => {
    removed.push([...((filters?.queryKey ?? []) as unknown[])]);
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidated, removed };
}

const DETAIL_KEY = [...cleanerKeys.detail(TENANT, "task-1")];
const CONTEXT_KEY = [...cleanerKeys.context(TENANT, "task-1")];
const CHECKLIST_KEY = [...cleanerKeys.checklist(TENANT, "task-1")];
const LIST_PREFIX = [...cleanerKeys.listPrefix(TENANT)];
const PHOTO_REQ_KEY = [...cleanerKeys.photoRequirements(TENANT, "task-1")];
const PHOTOS_KEY = [...cleanerKeys.photos(TENANT, "task-1")];

describe("useCleanerTaskCycleAction — accept / start (R3)", () => {
  beforeEach(() => {
    acceptMock.mockReset();
    acceptMock.mockResolvedValue(TASK);
    startMock.mockReset();
    startMock.mockResolvedValue(TASK);
  });

  it("accept invalidates detail + list prefix, nothing else", async () => {
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskCycleAction("accept"),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(acceptMock).toHaveBeenCalledWith(TENANT, "task-1");
    expect(invalidated).toEqual([DETAIL_KEY, LIST_PREFIX]);
    expect(removed).toEqual([]);
  });

  it("start invalidates detail + list prefix", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskCycleAction("start"),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(startMock).toHaveBeenCalledWith(TENANT, "task-1");
    expect(invalidated).toEqual([DETAIL_KEY, LIST_PREFIX]);
  });

  it("a 409 still invalidates and does not retry (R3.4)", async () => {
    acceptMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskCycleAction("accept"),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(acceptMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([DETAIL_KEY, LIST_PREFIX]);
  });
});

describe("useCleanerTaskCycleAction — completeChecklistItem (R4)", () => {
  beforeEach(() => {
    completeChecklistItemMock.mockReset();
    completeChecklistItemMock.mockResolvedValue(ITEM);
  });

  it("invalidates detail + checklist + list prefix", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskCycleAction("completeChecklistItem"),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1", itemId: "kitchen" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(completeChecklistItemMock).toHaveBeenCalledWith(
      TENANT,
      "task-1",
      "kitchen",
    );
    expect(invalidated).toEqual([DETAIL_KEY, CHECKLIST_KEY, LIST_PREFIX]);
  });

  it("requires itemId", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskCycleAction("completeChecklistItem"),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/itemId/);
  });
});

describe("useCleanerTaskCycleAction — reportIncident (R6)", () => {
  beforeEach(() => {
    reportIncidentMock.mockReset();
    reportIncidentMock.mockResolvedValue(ACK);
  });

  it("invalidates detail + list prefix, never photo requirements or photos", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useCleanerTaskCycleAction("reportIncident"),
      { wrapper },
    );

    result.current.mutate({
      taskId: "task-1",
      input: { title: "Caldera rota", description: "Sale agua" },
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(reportIncidentMock).toHaveBeenCalledWith(TENANT, "task-1", {
      title: "Caldera rota",
      description: "Sale agua",
    });
    expect(invalidated).toEqual([DETAIL_KEY, LIST_PREFIX]);
  });
});

describe("useRejectCleaningTask (R3.3, R3.4)", () => {
  beforeEach(() => {
    rejectMock.mockReset();
    rejectMock.mockResolvedValue(TASK);
  });

  it("removes detail, invalidates the list and calls onRejected (R3.3)", async () => {
    const onRejected = vi.fn();
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(
      () => useRejectCleaningTask({ onRejected }),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(removed).toEqual([DETAIL_KEY, CONTEXT_KEY]);
    expect(invalidated).toEqual([LIST_PREFIX]);
    expect(onRejected).toHaveBeenCalledOnce();
  });

  it("a reject that fails leaves the task in place and refreshes it (R3.4)", async () => {
    rejectMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const onRejected = vi.fn();
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(
      () => useRejectCleaningTask({ onRejected }),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(removed).toEqual([]);
    expect(invalidated).toEqual([DETAIL_KEY, LIST_PREFIX]);
    expect(onRejected).not.toHaveBeenCalled();
  });
});

describe("useCompleteCleaningTask (R7.1, R7.2)", () => {
  beforeEach(() => {
    completeMock.mockReset();
    completeMock.mockResolvedValue(TASK);
  });

  it("invalidates detail + list prefix and calls onCompleted (R7.2)", async () => {
    const onCompleted = vi.fn();
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(
      () => useCompleteCleaningTask({ onCompleted }),
      { wrapper },
    );

    result.current.mutate({ taskId: "task-1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(completeMock).toHaveBeenCalledWith(TENANT, "task-1");
    expect(invalidated).toEqual([DETAIL_KEY, LIST_PREFIX]);
    expect(removed).toEqual([]);
    expect(onCompleted).toHaveBeenCalledOnce();
  });
});

describe("useUploadCleaningPhoto (R5.4, R5.5)", () => {
  beforeEach(() => {
    uploadPhotoMock.mockReset();
    uploadPhotoMock.mockResolvedValue(PHOTO);
  });

  it("invalidates photoRequirements + photos of that task (R5.4)", async () => {
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(
      () => useUploadCleaningPhoto(),
      { wrapper },
    );

    result.current.mutate({
      taskId: "task-1",
      photoType: "kitchen",
      file: new File(["b"], "k.jpg", { type: "image/jpeg" }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(uploadPhotoMock).toHaveBeenCalledWith(
      TENANT,
      "task-1",
      "kitchen",
      expect.any(File),
    );
    expect(invalidated).toEqual([PHOTO_REQ_KEY, PHOTOS_KEY]);
    expect(removed).toEqual([]);
  });

  it("a 409 also invalidates the detail, so the reason can be read (R5.5)", async () => {
    uploadPhotoMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "x" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useUploadCleaningPhoto(),
      { wrapper },
    );

    result.current.mutate({
      taskId: "task-1",
      photoType: "kitchen",
      file: new File(["b"], "k.jpg"),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(uploadPhotoMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([PHOTO_REQ_KEY, PHOTOS_KEY, DETAIL_KEY]);
  });
});