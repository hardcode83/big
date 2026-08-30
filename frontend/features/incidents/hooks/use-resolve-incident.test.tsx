import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { HttpIncidentsSource } from "../data/http/http-incidents-source";
import type { IncidentDetailDto } from "../data";
import { useResolveIncident } from "./use-resolve-incident";

const resolveIncident = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", () => ({
  getIncidentsDataSource: () =>
    ({
      listIncidents: vi.fn(),
      getIncident: vi.fn(),
      resolveIncident,
    }) as unknown as HttpIncidentsSource,
}));

const resolved: IncidentDetailDto = {
  id: "incident-1",
  propertyId: "property-1",
  reservationId: null,
  source: "GUEST",
  category: "OTHER",
  severity: "MEDIUM",
  status: "RESOLVED",
  title: "Broken handle",
  description: "Front door handle loose",
  aiSummary: null,
  assignedTechnicianId: null,
  ownerApprovalRequired: false,
  estimatedCost: null,
  approvedCost: null,
  finalCost: "12.50",
  // `etaAt` and `materials` joined IncidentDetailDto in `tech-app`, whose
  // proposal declares that widening in scope. The dashboard's close does not
  // send `materials` (its D7), so the resolved fixture carries it null.
  etaAt: null,
  materials: null,
  resolvedAt: "2026-08-22T18:00:00Z",
  createdAt: "2026-08-22T17:00:00Z",
  updatedAt: "2026-08-22T18:00:00Z",
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
  resolveIncident.mockReset().mockResolvedValue(resolved);
});

describe("useResolveIncident (R2.3, R3.1, R3.2, design D5)", () => {
  it("forwards finalCost verbatim to the source — no other field", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useResolveIncident(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ incidentId: "incident-1", finalCost: "12.50" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(resolveIncident).toHaveBeenCalledWith(
      "tenant-1",
      "incident-1",
      "12.50",
    );
    expect(resolveIncident).toHaveBeenCalledTimes(1);
  });

  it("invalidates stalls, incidents, dashboard cards, and timelines (D5, R6)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useResolveIncident(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ incidentId: "incident-1", finalCost: 12.5 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const called = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(called).toEqual(
      expect.arrayContaining([
        ["tenant", "tenant-1", "blocked-transitions"],
        ["tenant", "tenant-1", "dashboard-cards"],
      ]),
    );
    expect(
      called.some(
        (key) =>
          Array.isArray(key) &&
          key[0] === "tenant" &&
          key[1] === "tenant-1" &&
          key[2] === "incidents-list",
      ),
    ).toBe(true);
    expect(
      called.some(
        (key) =>
          Array.isArray(key) &&
          key[0] === "tenant" &&
          key[1] === "tenant-1" &&
          key[2] === "property-timeline",
      ),
    ).toBe(true);
  });

  it("invalidates after a 4xx too (R3.3)", async () => {
    resolveIncident.mockRejectedValueOnce(
      new ApiError({
        code: "INCIDENT_RESOLVE_FORBIDDEN",
        message: "no permission",
        status: 403,
      }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useResolveIncident(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ incidentId: "incident-1", finalCost: "12.50" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const called = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(called).toEqual(
      expect.arrayContaining([
        ["tenant", "tenant-1", "blocked-transitions"],
        ["tenant", "tenant-1", "dashboard-cards"],
      ]),
    );
  });

  it("never retries a rejected write", async () => {
    resolveIncident.mockRejectedValue(
      new ApiError({
        code: "INCIDENT_RESOLVE_FORBIDDEN",
        message: "no permission",
        status: 403,
      }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useResolveIncident(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ incidentId: "incident-1", finalCost: "12.50" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(resolveIncident).toHaveBeenCalledTimes(1);
  });

  it("never writes the cache optimistically", async () => {
    const { setQueryData, Wrapper } = harness();
    const { result } = renderHook(() => useResolveIncident(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ incidentId: "incident-1", finalCost: "12.50" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(setQueryData).not.toHaveBeenCalled();
  });

  it("does not invalidate another tenant's entries", async () => {
    const { client, Wrapper } = harness();
    const otherTenant = ["tenant", "tenant-2", "blocked-transitions", 1];
    client.setQueryData(otherTenant, {
      data: [],
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    });

    const { result } = renderHook(() => useResolveIncident(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ incidentId: "incident-1", finalCost: "12.50" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(otherTenant)?.isInvalidated).toBe(false);
  });
});