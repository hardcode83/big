import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type {
  CleanerSummary,
  CleaningDataSource,
  CleaningTask,
  CleaningTaskFilters,
  PaginatedResponse,
  PropertySummary,
} from "../data";
import {
  useCleanerDirectory,
  useCleaningTasks,
  usePropertyDirectory,
} from "./use-cleaning-data";

const listTasks = vi.hoisted(() => vi.fn());
const listCleaners = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const assignTask = vi.hoisted(() => vi.fn());
const cancelTask = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getCleaningDataSource: (): CleaningDataSource => ({
    listTasks,
    listCleaners,
    listProperties,
    assignTask,
    cancelTask,
  }),
}));

function page(data: CleaningTask[]): PaginatedResponse<CleaningTask> {
  return { data, total: data.length, page: 1, per_page: 20, total_pages: 1 };
}

const cleaners: CleanerSummary[] = [
  { id: "cleaner-1", name: "Marta Ruiz", isActive: true },
];
const properties: PropertySummary[] = [
  { id: "property-1", name: "Redes 11", internalCode: "REDES11" },
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
  listTasks.mockReset().mockResolvedValue(page([]));
  listCleaners.mockReset().mockResolvedValue(cleaners);
  listProperties.mockReset().mockResolvedValue(properties);
});

describe("useCleaningTasks (R1.1, R3.1–R3.3)", () => {
  it("passes the filters and the page through to listTasks unchanged", async () => {
    const filters: CleaningTaskFilters = {
      propertyId: "property-7",
      status: "CREATED",
    };
    const { result } = renderHook(() => useCleaningTasks(filters, 4), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listTasks).toHaveBeenCalledWith(
      "tenant-from-session",
      filters,
      4,
    );
  });

  it("uses the tenant from the session, never an argument", async () => {
    const { result } = renderHook(() => useCleaningTasks({}, 1), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listTasks.mock.calls[0][0]).toBe("tenant-from-session");
  });

  it("surfaces a 4xx as an error state without retrying it", async () => {
    listTasks.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    const { result } = renderHook(() => useCleaningTasks({}, 1), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(listTasks).toHaveBeenCalledTimes(1);
  });
});

describe("catalog queries are shared, not per row (R2.5)", () => {
  it("fetches each catalog once with two task pages mounted at the same time", async () => {
    const Wrapper = wrapper();
    const { result } = renderHook(
      () => {
        const first = useCleaningTasks({}, 1);
        const second = useCleaningTasks({}, 2);
        const cleanerDirectory = useCleanerDirectory();
        const propertyDirectory = usePropertyDirectory();
        return { first, second, cleanerDirectory, propertyDirectory };
      },
      { wrapper: Wrapper },
    );

    await waitFor(() => {
      expect(result.current.cleanerDirectory.isSuccess).toBe(true);
      expect(result.current.propertyDirectory.isSuccess).toBe(true);
      expect(result.current.first.isSuccess).toBe(true);
      expect(result.current.second.isSuccess).toBe(true);
    });

    expect(listCleaners).toHaveBeenCalledTimes(1);
    expect(listProperties).toHaveBeenCalledTimes(1);
    // Two distinct pages are two distinct keys, so the list itself does refetch.
    expect(listTasks).toHaveBeenCalledTimes(2);
  });

  it("does not refetch a catalog when the filters change", async () => {
    const Wrapper = wrapper();
    const { result, rerender } = renderHook(
      ({ filters }: { filters: CleaningTaskFilters }) => {
        useCleanerDirectory();
        usePropertyDirectory();
        return useCleaningTasks(filters, 1);
      },
      { wrapper: Wrapper, initialProps: { filters: {} as CleaningTaskFilters } },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender({ filters: { status: "COMPLETED" } });
    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));

    expect(listCleaners).toHaveBeenCalledTimes(1);
    expect(listProperties).toHaveBeenCalledTimes(1);
  });
});

describe("useCleanerDirectory / usePropertyDirectory (R2.1, R2.2)", () => {
  it("resolves the catalogs the row needs to name a property and a cleaner", async () => {
    const { result } = renderHook(
      () => ({
        cleanerDirectory: useCleanerDirectory(),
        propertyDirectory: usePropertyDirectory(),
      }),
      { wrapper: wrapper() },
    );

    await waitFor(() => {
      expect(result.current.cleanerDirectory.isSuccess).toBe(true);
      expect(result.current.propertyDirectory.isSuccess).toBe(true);
    });
    expect(result.current.cleanerDirectory.data).toEqual(cleaners);
    expect(result.current.propertyDirectory.data).toEqual(properties);
    expect(listCleaners).toHaveBeenCalledWith("tenant-from-session");
    expect(listProperties).toHaveBeenCalledWith("tenant-from-session");
  });
});
