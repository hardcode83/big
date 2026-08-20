import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { useIncident, useIncidents } from "./use-incidents";
import { incidentsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const listMock = vi.fn();
const detailMock = vi.fn();
const getIncidentsDataSource = vi.spyOn(dataModule, "getIncidentsDataSource");

getIncidentsDataSource.mockImplementation(
  () =>
    ({
      listIncidents: listMock,
      getIncident: detailMock,
    }) as unknown as ReturnType<typeof dataModule.getIncidentsDataSource>,
);

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
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
  items: [
    {
      id: "i1",
      status: "OPEN",
      severity: "LOW",
      category: "WIFI",
      source: "GUEST",
      title: "WiFi",
      createdAt: "2026-08-12T08:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  perPage: 20,
} as const;

const DETAIL = {
  id: "i1",
  propertyId: "p1",
  reservationId: null,
  source: "GUEST",
  category: "WIFI",
  severity: "LOW",
  status: "OPEN",
  title: "WiFi",
  description: "",
  aiSummary: null,
  assignedTechnicianId: null,
  ownerApprovalRequired: false,
  estimatedCost: null,
  approvedCost: null,
  finalCost: null,
  resolvedAt: null,
  createdAt: "2026-08-12T08:00:00Z",
  updatedAt: "2026-08-12T08:00:00Z",
} as const;

describe("useIncidents / useIncident", () => {
  beforeEach(() => {
    listMock.mockReset();
    detailMock.mockReset();
    listMock.mockResolvedValue(LIST_PAGE);
    detailMock.mockResolvedValue(DETAIL);
  });

  it("useIncidents calls the source with the supplied filters", async () => {
    const { result } = renderHook(
      () => useIncidents({ status: "OPEN", severity: "HIGH" }),
      { wrapper: freshWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", {
      status: "OPEN",
      severity: "HIGH",
    });
  });

  it("useIncident calls the source with the id", async () => {
    const { result } = renderHook(() => useIncident("i1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(detailMock).toHaveBeenCalledWith("tenant-from-session", "i1");
  });

  it("scopes the query keys by tenant and includes the filters (D4)", async () => {
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    renderHook(() => useIncidents({ status: "OPEN" }), { wrapper });
    await waitFor(() => {
      expect(
        client.getQueryData(
          incidentsKeys.list("tenant-from-session", { status: "OPEN" }),
        ),
      ).toBeDefined();
    });
  });

  it("does NOT retry 4xx errors (smoke test of retryPolicy wiring)", async () => {
    detailMock.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "not_found", message: "x" }),
    );
    const { result } = renderHook(() => useIncident("i1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(detailMock).toHaveBeenCalledTimes(1);
  });
});