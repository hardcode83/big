import type { ReactNode } from "react";
import {
  QueryClient,
  QueryClientProvider,
  type UseMutationResult,
} from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import {
  useCancelReservation,
  useCreateReservation,
  useReservation,
  useReservations,
  useUpdateReservation,
} from "./use-reservations";
import * as dataModule from "../data";
import { reservationsKeys } from "./query-keys";

const authUser = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({ useAuth: authUser }));

const listMock = vi.fn();
const detailMock = vi.fn();
const createMock = vi.fn();
const updateMock = vi.fn();
const cancelMock = vi.fn();
const getReservationsDataSource = vi.spyOn(dataModule, "getReservationsDataSource");

getReservationsDataSource.mockImplementation(
  () =>
    ({
      listReservations: listMock,
      getReservation: detailMock,
      createReservation: createMock,
      updateReservation: updateMock,
      cancelReservation: cancelMock,
    }) as unknown as ReturnType<typeof dataModule.getReservationsDataSource>,
);

// Wrapper that does NOT override the QueryClient-level retry. The previous
// wrapper set `defaultOptions.queries.retry = false`, which MASKED the
// hook's retry config — removing `retry: retryPolicy` from the hook left the
// test passing. The wrapper below does not override retry, so the hook's
// `retry: retryPolicy` is the policy TanStack Query consults.
function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        // Reduce the default exponential backoff so the test settles
        // fast under real timers (the 5xx retry path waits 1s + 2s).
        retryDelay: 100,
      },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

const LIST_PAGE = {
  data: [],
  page: 1,
  perPage: 20,
  total: 0,
  totalPages: 0,
};

const DETAIL_PAYLOAD = {
  id: "reservation-1",
  propertyId: "property-1",
  status: "PENDING",
  checkInDate: "2026-08-12",
  checkOutDate: "2026-08-15",
  nights: 3,
  totalGuests: 2,
  guestId: null,
  channel: "MANUAL",
  currency: "EUR",
  grossAmount: null,
  paymentStatus: "PENDING",
  checkInTime: null,
  checkOutTime: null,
  adults: 0,
  children: 0,
  otaCommission: null,
  netAmount: null,
  cleaningRequired: false,
  accessStatus: "PENDING",
  externalChannelId: null,
  externalPmsId: null,
  internalNotes: null,
  specialRequests: null,
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
  guest: null,
} as const;

describe("useReservations / useReservation", () => {
  beforeEach(() => {
    authUser.mockReturnValue({ user: { tenant_id: "tenant-from-session" } });
    detailMock.mockReset();
    listMock.mockReset();
    createMock.mockReset().mockResolvedValue({ id: "reservation-1" });
    updateMock.mockReset().mockResolvedValue({ id: "reservation-1" });
    cancelMock.mockReset().mockResolvedValue(undefined);
  });

  it("useReservations calls the source with the filters it received", async () => {
    listMock.mockResolvedValue(LIST_PAGE);
    const filters = { status: "PENDING" as const, dateFrom: "2026-08-01" };
    const { result } = renderHook(() => useReservations(filters), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", filters);
  });

  it("useReservation calls the source with the id", async () => {
    detailMock.mockResolvedValue(DETAIL_PAYLOAD);
    const { result } = renderHook(() => useReservation("reservation-1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(detailMock).toHaveBeenCalledWith(
      "tenant-from-session",
      "reservation-1",
    );
  });

  it("cache keys include the tenantId and the filters (no key sharing across tenants)", () => {
    const filters = { status: "PENDING" as const };
    expect(reservationsKeys.list("tenant-A", filters)).toEqual([
      "tenant",
      "tenant-A",
      "reservations-list",
      { status: "PENDING" },
    ]);
    expect(reservationsKeys.list("tenant-B", filters)).toEqual([
      "tenant",
      "tenant-B",
      "reservations-list",
      { status: "PENDING" },
    ]);
    expect(reservationsKeys.detail("tenant-A", "reservation-1")).toEqual([
      "tenant",
      "tenant-A",
      "reservations-detail",
      "reservation-1",
    ]);
  });

  async function expectMutationInvalidation<T>(
    hook: () => UseMutationResult<unknown, Error, T>,
    variables: T,
    sourceMock: ReturnType<typeof vi.fn>,
    expectsDetail: boolean,
  ) {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3 }, queries: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => hook(), { wrapper: Wrapper });

    result.current.mutate(variables);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reservationsKeys.listPrefix("tenant-from-session"),
    });
    if (expectsDetail) {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: reservationsKeys.detail("tenant-from-session", "reservation-1"),
      });
    }
    expect(sourceMock).toHaveBeenCalledTimes(1);
  }

  it("create mutation does not retry and awaits tenant-scoped invalidation", async () => {
    await expectMutationInvalidation(
      useCreateReservation,
      { property_id: "property-1" } as never,
      createMock,
      false,
    );
  });

  it("update mutation invalidates list and detail after awaiting both", async () => {
    await expectMutationInvalidation(
      useUpdateReservation,
      { reservationId: "reservation-1", input: {} },
      updateMock,
      true,
    );
  });

  it("cancel mutation invalidates list and detail after awaiting both", async () => {
    await expectMutationInvalidation(
      useCancelReservation,
      { reservationId: "reservation-1" },
      cancelMock,
      true,
    );
  });

  async function expectFailedMutationInvalidation<T>(
    hook: () => UseMutationResult<unknown, Error, T>,
    variables: T,
    sourceMock: ReturnType<typeof vi.fn>,
    expectedInvalidations: number,
    reservationId?: string,
  ) {
    const failure = new ApiError({
      code: "CONFLICT",
      message: "opaque server message",
      status: 409,
    });
    sourceMock.mockRejectedValue(failure);
    let release!: () => void;
    const invalidation = new Promise<void>((resolve) => {
      release = resolve;
    });
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3, retryDelay: 0 } },
    });
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockImplementation(() => invalidation);
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => hook(), { wrapper: Wrapper });

    result.current.mutate(variables);
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(expectedInvalidations));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reservationsKeys.listPrefix("tenant-from-session"),
    });
    if (reservationId) {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: reservationsKeys.detail("tenant-from-session", reservationId),
      });
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["tenant", "tenant-from-session", "property-timeline"],
      });
    }
    expect(sourceMock).toHaveBeenCalledTimes(1);
    expect(result.current.isError).toBe(false);
    release();
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(sourceMock).toHaveBeenCalledTimes(1);
  }

  it("create mutation does not retry and awaits list invalidation after an error", async () => {
    await expectFailedMutationInvalidation(
      useCreateReservation,
      { property_id: "property-1" } as never,
      createMock,
      1,
    );
  });

  it("update mutation does not retry and awaits list/detail invalidation after an error", async () => {
    await expectFailedMutationInvalidation(
      useUpdateReservation,
      { reservationId: "reservation-1", input: {} },
      updateMock,
      3,
      "reservation-1",
    );
  });

  it("cancel mutation does not retry and awaits list/detail invalidation after an error", async () => {
    await expectFailedMutationInvalidation(
      useCancelReservation,
      { reservationId: "reservation-1" },
      cancelMock,
      3,
      "reservation-1",
    );
  });

  it.each([
    [null, "missing user"],
    [{}, "missing tenant id"],
    [{ tenant_id: 42 }, "malformed tenant id"],
    [{ tenant_id: "" }, "empty tenant id"],
    [{ tenant_id: "   " }, "blank tenant id"],
  ] as const)("rejects %s context (%s) with a stable internal code", (user, _label) => {
    authUser.mockReturnValue({ user });
    expect(() => renderHook(() => useReservations(), { wrapper: freshWrapper() })).toThrowError(
      expect.objectContaining({ code: "TENANT_CONTEXT_REQUIRED" }),
    );
  });

  it("does not finish until invalidation settles", async () => {
    let release!: () => void;
    const invalidation = new Promise<void>((resolve) => {
      release = resolve;
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi
      .spyOn(client, "invalidateQueries")
      .mockImplementation(() => invalidation);
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useCreateReservation(), { wrapper: Wrapper });
    result.current.mutate({ property_id: "property-1" } as never);
    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    expect(result.current.isSuccess).toBe(false);
    release();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("does not optimistically write reservation cache", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const setQueryData = vi.spyOn(client, "setQueryData");
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useUpdateReservation(), { wrapper: Wrapper });
    result.current.mutate({ reservationId: "reservation-1", input: {} });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(setQueryData).not.toHaveBeenCalled();
  });

  // The next two tests pin the wiring of `retry: retryPolicy` so that
  // removing or changing the retry config produces a red test. The previous
  // "smoke" only asserted that the source was reached, which was true with
  // any retry config at all.
  //
  // retryPolicy (`@/lib/api/retry-policy.ts`):
  //   - 4xx ApiError → false (no retry)
  //   - non-4xx → true up to `failureCount < 2` (i.e. up to 2 retries → 3 calls)
  it("useReservation does NOT retry on 4xx (retryPolicy returns false for ApiError 4xx)", async () => {
    detailMock.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
    );
    const { result } = renderHook(() => useReservation("unknown"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true), {
      timeout: 3000,
    });
    // 1 initial + 0 retries = 1 call.
    expect(detailMock).toHaveBeenCalledTimes(1);
  });

  it("useReservation retries on 5xx (retryPolicy returns true up to failureCount < 2)", async () => {
    detailMock.mockRejectedValue(
      new ApiError({ code: "SERVER", message: "boom", status: 500 }),
    );
    const { result } = renderHook(() => useReservation("server-error"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true), {
      timeout: 5000,
    });
    // 1 initial + 2 retries = 3 calls. If the hook removed
    // `retry: retryPolicy` and fell back to TanStack's default
    // (3 retries), this would be 4. If it changed to `retry: false`,
    // this would be 1.
    expect(detailMock).toHaveBeenCalledTimes(3);
  });
});
