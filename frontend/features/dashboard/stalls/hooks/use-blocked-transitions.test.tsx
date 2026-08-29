import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const useAuth = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ useAuth }));

import type {
  BlockedTransitionPage,
  BlockedTransitionSummary,
} from "../data";
import { useBlockedTransitions } from "./use-blocked-transitions";

function makeStall(
  partial: Partial<BlockedTransitionSummary> & {
    property_id: string;
    reservation_id: string;
    trigger: string;
    blocking_state: string;
    due_since: string;
  },
): BlockedTransitionSummary {
  return {
    property_code: partial.property_id.toUpperCase(),
    ...partial,
  } as BlockedTransitionSummary;
}

function wrap(
  queryClient: QueryClient,
  children: ReactNode,
): React.ReactElement {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function setTenant(tenantId: string) {
  useAuth.mockReturnValue({ user: { tenant_id: tenantId } });
}

afterEach(() => {
  useAuth.mockReset();
});

describe("useBlockedTransitions (R1.1, R1.4)", () => {
  let queryClient: QueryClient;
  let mock: { listBlockedTransitions: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mock = { listBlockedTransitions: vi.fn() };
    vi.doMock("../data", () => ({
      getStallsDataSource: () => mock,
    }));
  });

  it("sorts stalls by due_since ascending with deterministic tie-break", async () => {
    setTenant("tenant-a");
    const unsorted: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-3",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-23T13:00:00Z",
      }),
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-23T13:00:00Z", // same due_since, tie-break on reservation_id
      }),
      makeStall({
        property_id: "redes11",
        reservation_id: "r-2",
        trigger: "CHECKIN_WINDOW_OPENED",
        blocking_state: "MAINTENANCE_REQUIRED",
        due_since: "2026-08-22T13:00:00Z",
      }),
      makeStall({
        property_id: "pajaritos8",
        reservation_id: "r-4",
        trigger: "CHECKOUT_TIME_REACHED",
        blocking_state: "CRITICAL_INCIDENT",
        due_since: "2026-08-21T13:00:00Z",
      }),
    ];
    const page: BlockedTransitionPage = {
      data: unsorted,
      total: unsorted.length,
      page: 1,
      per_page: unsorted.length,
      total_pages: 1,
    };
    mock.listBlockedTransitions.mockResolvedValue(page);

    // Import after the doMock is in place so the hook picks up the override.
    const { useBlockedTransitions: hook } = await import(
      "./use-blocked-transitions"
    );
    const { result } = renderHook(() => hook(), {
      wrapper: ({ children }) => wrap(queryClient, children),
    });

    await waitFor(() => {
      expect(result.current.data).toEqual(page);
    });

    const redes11 = result.current.byPropertyId.get("redes11");
    const pajaritos8 = result.current.byPropertyId.get("pajaritos8");
    expect(redes11?.map((s) => s.reservation_id)).toEqual([
      "r-2",
      "r-1",
      "r-3",
    ]);
    expect(pajaritos8?.map((s) => s.reservation_id)).toEqual(["r-4"]);
  });

  it("isolates stalls by tenant (R1.4)", async () => {
    // Tenant A first, then switch to tenant B and assert A's data does not
    // bleed into B's view — the cache key includes the tenant (R1.4).
    setTenant("tenant-a");
    const tenantAStalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-23T13:00:00Z",
      }),
    ];
    mock.listBlockedTransitions.mockImplementation(async (tenantId: string) => {
      if (tenantId === "tenant-a") {
        return {
          data: tenantAStalls,
          total: 1,
          page: 1,
          per_page: 1,
          total_pages: 1,
        };
      }
      return {
        data: [],
        total: 0,
        page: 1,
        per_page: 0,
        total_pages: 0,
      };
    });

    const { useBlockedTransitions: hook } = await import(
      "./use-blocked-transitions"
    );
    const wrapper = ({ children }: { children: ReactNode }) =>
      wrap(queryClient, children);

    const { result, rerender } = renderHook(() => hook(), { wrapper });
    await waitFor(() => {
      expect(result.current.data?.data).toEqual(tenantAStalls);
    });

    setTenant("tenant-b");
    rerender();
    await waitFor(() => {
      expect(result.current.data?.data).toEqual([]);
    });
    expect(result.current.byPropertyId.has("redes11")).toBe(false);
    // Both queries were issued — one per tenant — and the second never
    // returned tenant A's row.
    const tenantIds = mock.listBlockedTransitions.mock.calls.map(
      (call) => call[0],
    );
    expect(new Set(tenantIds)).toEqual(new Set(["tenant-a", "tenant-b"]));
  });
});