import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { CleaningDataSource, CleaningPhotoDto } from "../data";
import { cleaningKeys } from "./query-keys";
import { useCleaningTaskPhotos } from "./use-cleaning-photos";

const listPhotos = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getCleaningDataSource: (): CleaningDataSource =>
    ({
      listPhotos,
    }) as unknown as CleaningDataSource,
}));

const photos: CleaningPhotoDto[] = [
  {
    id: "photo-1",
    cleaningTaskId: "task-1",
    photoType: "KITCHEN",
    uploadedBy: "cleaner-1",
    createdAt: "2026-09-18T09:00:00Z",
    url: "/api/v1/cleaning-photos/photo-1?exp=1&sig=a",
  },
];

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
  listPhotos.mockReset().mockResolvedValue(photos);
});

describe("useCleaningTaskPhotos (R2.1)", () => {
  it("starts in a pending state", () => {
    const { result } = renderHook(() => useCleaningTaskPhotos("task-1"), {
      wrapper: wrapper(),
    });

    expect(result.current.isPending).toBe(true);
  });

  it("asks the source for the task's photos under the session tenant", async () => {
    const { result } = renderHook(() => useCleaningTaskPhotos("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listPhotos).toHaveBeenCalledWith("tenant-1", "task-1");
    expect(result.current.data).toEqual(photos);
  });

  it("keys the query on cleaningKeys.photos(tenantId, taskId)", async () => {
    const client = new QueryClient();
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    }

    const { result } = renderHook(() => useCleaningTaskPhotos("task-1"), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(
      client.getQueryData(cleaningKeys.photos("tenant-1", "task-1")),
    ).toEqual(photos);
  });

  it("surfaces an ApiError on failure", async () => {
    listPhotos.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
    );
    const { result } = renderHook(() => useCleaningTaskPhotos("task-1"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect((result.current.error as ApiError).status).toBe(404);
  });
});
