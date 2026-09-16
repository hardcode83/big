import type { ReactNode } from "react";
import { act } from "react";
import {
  focusManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useTranslation } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n/client-provider";

import {
  DASHBOARD_CARDS_POLL_INTERVAL_MS,
  retryPolicy,
  useDashboardCards,
  usePropertyDetail,
  usePropertyTimeline,
} from "./use-dashboard-data";

vi.mock("@/lib/auth", () => ({
  useAuth: vi.fn(() => ({ user: { tenant_id: "tenant-from-session" } })),
}));

const { requestMock } = vi.hoisted(() => {
  const requestMock = vi.fn(
    async (path: string, options?: { pathParams?: { property_id?: string } }) => {
      if (path === "/api/v1/dashboard/properties") {
        return {
          data: [{
            property_id: "property-1",
            property_code: "REDES11",
            operational_state: "AWAITING_CLEANING",
            current_or_next_reservation: null,
            cleaning_status: null,
            open_incidents_count: 0,
            next_action: null,
            last_event_label: null,
            last_event_at: null,
          }],
          total: 1,
          page: 1,
          per_page: 20,
          total_pages: 1,
        };
      }
      if (path === "/api/v1/properties/{property_id}/dashboard") {
        if (options?.pathParams?.property_id === "unknown") {
          throw new ApiError({
            code: "NOT_FOUND",
            message: "not found",
            status: 404,
          });
        }
        return {
          property_id: "property-1",
          property_code: "REDES11",
          operational_state: "AWAITING_CLEANING",
          current_or_next_reservation: null,
          guest: null,
          access: null,
          cleaning_status: null,
          last_cleaning_photos: [],
          open_incidents: [],
          financial: null,
          notes: null,
          pending_approvals: [],
        };
      }
      return {
        data: [{
          id: "event-1",
          occurred_at: "2026-08-10T09:00:00Z",
          actor_type: "GUEST",
          event_type: "GUEST_MESSAGE_RECEIVED",
          severity: "INFO",
          title: "Guest message",
          description: null,
        }],
        total: 1,
        page: 1,
        per_page: 20,
        total_pages: 1,
      };
    },
  );
  return { requestMock };
});

const mockedUseAuth = vi.mocked(useAuth);

vi.mock("@/lib/api/authenticated-client", () => ({
  createAuthenticatedClients: () => ({
    apiClient: { request: requestMock },
    refreshTokens: async () => ({ accessToken: "access", refreshToken: "refresh" }),
  }),
  notifySessionExpired: vi.fn(),
}));

function wrapper(locale: "es" | "en" = "es") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider locale={locale}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </I18nProvider>
    );
  };
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function dashboardCardsResponse(propertyId: string) {
  return {
    data: [{
      property_id: propertyId,
      property_code: propertyId.toUpperCase(),
      operational_state: "AWAITING_CLEANING",
      current_or_next_reservation: null,
      cleaning_status: null,
      open_incidents_count: 0,
      next_action: null,
      last_event_label: null,
      last_event_at: null,
    }],
    total: 1,
    page: 1,
    per_page: 20,
    total_pages: 1,
  };
}

describe("retryPolicy (R2.3)", () => {
  it("never retries a 4xx client error (e.g. a 404 not-found)", () => {
    const err404 = new ApiError({ code: "NOT_FOUND", message: "no", status: 404 });
    expect(retryPolicy(0, err404)).toBe(false);
    const err422 = new ApiError({ code: "VALIDATION", message: "no", status: 422 });
    expect(retryPolicy(0, err422)).toBe(false);
  });

  it("retries a transient failure briefly, then gives up", () => {
    const err500 = new ApiError({ code: "SERVER", message: "boom", status: 500 });
    expect(retryPolicy(0, err500)).toBe(true);
    expect(retryPolicy(1, err500)).toBe(true);
    expect(retryPolicy(2, err500)).toBe(false);
    expect(retryPolicy(0, new Error("network"))).toBe(true);
  });
});

describe("dashboard data hooks (R4)", () => {
  it("useDashboardCards resolves HTTP cards through the composition point", async () => {
    const { result } = renderHook(() => useDashboardCards(), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data.length).toBeGreaterThan(0);
  });

  it("usePropertyDetail resolves a known property", async () => {
    const { result } = renderHook(() => usePropertyDetail("redes11"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.propertyCode).toBe("REDES11");
  });

  it("usePropertyDetail surfaces the 404 as an error state for an unknown id", async () => {
    const { result } = renderHook(() => usePropertyDetail("unknown"), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("usePropertyTimeline passes filters through to the source", async () => {
    const { result } = renderHook(
      () => usePropertyTimeline("pajaritos8", { actorType: "GUEST" }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.data.every((e) => e.actorType === "GUEST")).toBe(
      true,
    );
  });
});

describe("dashboard hooks react to a locale change (R2.1, R2.2, D7, D8)", () => {
  it("useDashboardCards produces a new query key and refetches when the active locale changes", async () => {
    requestMock.mockClear();

    const { result } = renderHook(
      () => ({
        query: useDashboardCards(),
        i18n: useTranslation().i18n,
      }),
      { wrapper: wrapper("es") },
    );

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
    const callsBeforeSwitch = requestMock.mock.calls.length;
    expect(callsBeforeSwitch).toBeGreaterThan(0);

    // A fresh QueryClient starts with no cached "en" entry, so switching
    // locale must produce a *new* cache key: the query goes back through its
    // loading state (D8 — no `keepPreviousData`) and the data source is
    // called again (R2.2's refetch), rather than reusing the "es" result.
    await act(async () => {
      await result.current.i18n.changeLanguage("en");
    });

    await waitFor(() =>
      expect(requestMock.mock.calls.length).toBeGreaterThan(callsBeforeSwitch),
    );
    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
  });

  it("usePropertyTimeline's query key changes with locale while filters and propertyId stay fixed", async () => {
    requestMock.mockClear();

    const { result } = renderHook(
      () => ({
        query: usePropertyTimeline("pajaritos8", { actorType: "GUEST" }),
        i18n: useTranslation().i18n,
      }),
      { wrapper: wrapper("es") },
    );

    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
    const callsBeforeSwitch = requestMock.mock.calls.length;

    await act(async () => {
      await result.current.i18n.changeLanguage("en");
    });

    await waitFor(() =>
      expect(requestMock.mock.calls.length).toBeGreaterThan(callsBeforeSwitch),
    );
  });
});

describe("useDashboardCards polling (R4)", () => {
  beforeEach(() => {
    requestMock.mockClear();
    mockedUseAuth.mockReturnValue({
      user: { tenant_id: "tenant-from-session" },
    } as never);
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    mockedUseAuth.mockReturnValue({
      user: { tenant_id: "tenant-from-session" },
    } as never);
    setVisibility("visible");
  });

  it("refetches cards at the nominal 30-second interval", async () => {
    expect(DASHBOARD_CARDS_POLL_INTERVAL_MS).toBe(30_000);
    vi.useFakeTimers();
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchOnWindowFocus: false },
      },
    });

    const { result } = renderHook(() => useDashboardCards(), {
      wrapper: ({ children }) => (
        <I18nProvider locale="es">
          <QueryClientProvider client={queryClient}>
            {children}
          </QueryClientProvider>
        </I18nProvider>
      ),
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.isSuccess).toBe(true);
    expect(requestMock).toHaveBeenCalledTimes(1);
    const settledMountCalls = requestMock.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_999);
    });
    expect(requestMock).toHaveBeenCalledTimes(settledMountCalls);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(requestMock).toHaveBeenCalledTimes(settledMountCalls + 1);
    expect(requestMock).toHaveBeenLastCalledWith(
      "/api/v1/dashboard/properties",
    );
  });

  it("usePropertyDetail does not refetch after 30 seconds", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => usePropertyDetail("redes11"), {
      wrapper: wrapper(),
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.isSuccess).toBe(true);
    expect(requestMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("usePropertyTimeline does not refetch after 30 seconds", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(
      () => usePropertyTimeline("pajaritos8", { actorType: "GUEST" }),
      { wrapper: wrapper() },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.isSuccess).toBe(true);
    expect(requestMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("pauses polling while hidden and resumes without a focus refetch", async () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchOnWindowFocus: false },
      },
    });

    const { result } = renderHook(() => useDashboardCards(), {
      wrapper: ({ children }) => (
        <I18nProvider locale="es">
          <QueryClientProvider client={queryClient}>
            {children}
          </QueryClientProvider>
        </I18nProvider>
      ),
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.isSuccess).toBe(true);
    expect(requestMock).toHaveBeenCalledTimes(1);

    setVisibility("hidden");
    await act(async () => {
      await Promise.resolve();
    });
    expect(focusManager.isFocused()).toBe(false);
    const callsWhenHidden = requestMock.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(
        DASHBOARD_CARDS_POLL_INTERVAL_MS * 4,
      );
    });
    expect(requestMock).toHaveBeenCalledTimes(callsWhenHidden);

    setVisibility("visible");
    window.dispatchEvent(new Event("focus"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(focusManager.isFocused()).toBe(true);
    expect(requestMock).toHaveBeenCalledTimes(callsWhenHidden);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DASHBOARD_CARDS_POLL_INTERVAL_MS);
    });
    expect(requestMock).toHaveBeenCalledTimes(callsWhenHidden + 1);
  });

  it("uses a tenant-scoped query key when the authenticated tenant changes", async () => {
    const tenantARequest = deferred<
      ReturnType<typeof dashboardCardsResponse>
    >();
    const tenantBRequest = deferred<
      ReturnType<typeof dashboardCardsResponse>
    >();
    requestMock
      .mockImplementationOnce(() => tenantARequest.promise)
      .mockImplementationOnce(() => tenantBRequest.promise);
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchOnWindowFocus: false },
      },
    });
    mockedUseAuth.mockReturnValue({ user: { tenant_id: "tenant-a" } } as never);
    const { result, rerender } = renderHook(() => useDashboardCards(), {
      wrapper: ({ children }) => (
        <I18nProvider locale="es">
          <QueryClientProvider client={queryClient}>
            {children}
          </QueryClientProvider>
        </I18nProvider>
      ),
    });

    await waitFor(() => expect(requestMock).toHaveBeenCalledTimes(1));
    mockedUseAuth.mockReturnValue({ user: { tenant_id: "tenant-b" } } as never);
    rerender();

    await waitFor(() => expect(requestMock).toHaveBeenCalledTimes(2));
    expect(result.current.data).toBeUndefined();

    tenantARequest.resolve(dashboardCardsResponse("tenant-a-property"));
    await waitFor(() =>
      expect(
        queryClient.getQueryData([
          "tenant",
          "tenant-a",
          "dashboard-cards",
          "es",
        ]),
      ).toMatchObject({ data: [{ propertyId: "tenant-a-property" }] }),
    );
    expect(result.current.data).toBeUndefined();

    tenantBRequest.resolve(dashboardCardsResponse("tenant-b-property"));
    await waitFor(() =>
      expect(result.current.data).toMatchObject({
        data: [{ propertyId: "tenant-b-property" }],
      }),
    );
    expect(
      queryClient.getQueryData([
        "tenant",
        "tenant-b",
        "dashboard-cards",
        "es",
      ]),
    ).toMatchObject({ data: [{ propertyId: "tenant-b-property" }] });
  });
});
