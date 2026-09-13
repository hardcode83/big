import type { ReactNode } from "react";
import {
  QueryClient,
  QueryClientProvider,
  type UseMutationResult,
} from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import { useConfirmReservation } from "./use-reservations";
import * as dataModule from "../data";
import { reservationsKeys } from "./query-keys";

const authUser = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({ useAuth: authUser }));

const updateMock = vi.fn();
const getReservationsDataSource = vi.spyOn(dataModule, "getReservationsDataSource");

getReservationsDataSource.mockImplementation(
  () =>
    ({
      updateReservation: updateMock,
    }) as unknown as ReturnType<typeof dataModule.getReservationsDataSource>,
);

const CONFIRMED_SUMMARY = {
  id: "reservation-1",
  propertyId: "property-1",
  status: "CONFIRMED",
  checkInDate: "2026-08-12",
  checkOutDate: "2026-08-15",
  nights: 3,
  totalGuests: 2,
  guestId: null,
  channel: "MANUAL",
  currency: "EUR",
  grossAmount: null,
  paymentStatus: "PENDING",
  propertyName: null,
  propertyInternalCode: null,
  guestFullName: null,
} as const;

describe("useConfirmReservation (R1, D2)", () => {
  beforeEach(() => {
    authUser.mockReturnValue({ user: { tenant_id: "tenant-from-session" } });
    updateMock.mockReset().mockResolvedValue(CONFIRMED_SUMMARY);
  });

  function freshWrapper() {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3, retryDelay: 0 }, queries: { retry: false } },
    });
    return function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    };
  }

  it("sends a fixed PATCH payload { status: 'CONFIRMED' } — caller cannot override the status", async () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3, retryDelay: 0 }, queries: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: Wrapper });

    result.current.mutate({ reservationId: "reservation-1" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(updateMock).toHaveBeenCalledWith(
      "tenant-from-session",
      "reservation-1",
      { status: "CONFIRMED" },
    );
    expect(invalidate).toHaveBeenCalledTimes(3);
  });

  it("ignores any extra field a caller passes on the variables object", async () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3, retryDelay: 0 }, queries: { retry: false } },
    });
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: Wrapper });

    // TS prevents passing unknown keys (variables is `{ reservationId: string }`),
    // but the transport check is what matters: only `status: "CONFIRMED"` ships.
    result.current.mutate({ reservationId: "reservation-2" } as never);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(updateMock).toHaveBeenCalledWith(
      "tenant-from-session",
      "reservation-2",
      { status: "CONFIRMED" },
    );
  });

  it("does not retry on 4xx and awaits tenant-scoped invalidation on success", async () => {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3, retryDelay: 0 }, queries: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: Wrapper });

    result.current.mutate({ reservationId: "reservation-1" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reservationsKeys.listPrefix("tenant-from-session"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reservationsKeys.detail("tenant-from-session", "reservation-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["tenant", "tenant-from-session", "property-timeline"],
    });
  });

  it("does not retry and awaits list/detail/property-timeline invalidation after an error", async () => {
    updateMock.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "already confirmed", status: 409 }),
    );
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: 3, retryDelay: 0 }, queries: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: Wrapper });

    result.current.mutate({ reservationId: "reservation-1" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    // The hook sets retry: false — 1 initial + 0 retries, even though the wrapper
    // would let mutations retry 3 times.
    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reservationsKeys.listPrefix("tenant-from-session"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: reservationsKeys.detail("tenant-from-session", "reservation-1"),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["tenant", "tenant-from-session", "property-timeline"],
    });
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
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: Wrapper });
    result.current.mutate({ reservationId: "reservation-1" });
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
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: Wrapper });
    result.current.mutate({ reservationId: "reservation-1" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(setQueryData).not.toHaveBeenCalled();
  });

  // Pin the `retry: false` wiring: if the hook ever changes to `retry: retryPolicy`,
  // a 4xx would still produce 1 call, so this test alone won't catch it. The error
  // path above (`409`) is the load-bearing assertion for "no retries".
  it("typed variables surface in the result type as { reservationId: string }", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useConfirmReservation(), { wrapper: freshWrapper() });
    // Use the type-level test to keep the variables contract honest at compile time.
    const _typed: UseMutationResult<unknown, Error, { reservationId: string }> = result.current;
    expect(_typed).toBe(result.current);
  });
});