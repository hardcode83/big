import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import {
  retryPolicy,
  useDashboardCards,
  usePropertyDetail,
  usePropertyTimeline,
} from "./use-dashboard-data";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

vi.mock("@/lib/api/authenticated-client", () => ({
  createAuthenticatedClients: () => ({
    apiClient: {
      request: async (path: string, options?: { pathParams?: { property_id?: string } }) => {
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
    },
    refreshTokens: async () => ({ accessToken: "access", refreshToken: "refresh" }),
  }),
  notifySessionExpired: vi.fn(),
}));

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
