import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import {
  useIncident,
  useIncidentContext,
  useIncidentPhotos,
  useIncidents,
} from "./use-incidents";
import { incidentsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const listMock = vi.fn();
const detailMock = vi.fn();
const contextMock = vi.fn();
const photosMock = vi.fn();
const getIncidentsDataSource = vi.spyOn(dataModule, "getIncidentsDataSource");

getIncidentsDataSource.mockImplementation(
  () =>
    ({
      listIncidents: listMock,
      getIncident: detailMock,
      getIncidentContext: contextMock,
      listPhotos: photosMock,
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
  etaAt: null,
  estimatedCost: null,
  approvedCost: null,
  finalCost: null,
  materials: null,
  resolvedAt: null,
  createdAt: "2026-08-12T08:00:00Z",
  updatedAt: "2026-08-12T08:00:00Z",
} as const;

const CONTEXT = {
  propertyName: "Piso Sol",
  propertyInternalCode: "MAD-01",
  addressLine1: "Calle Mayor 1",
  addressLine2: null,
  city: "Madrid",
  province: "Madrid",
  postalCode: "28013",
  country: "ES",
  timezone: "Europe/Madrid",
  accessNotes: null,
  assignmentNote: null,
} as const;

const PHOTOS = [
  {
    id: "ph1",
    incidentId: "i1",
    stage: "BEFORE",
    uploadedBy: "u1",
    createdAt: "2026-08-12T09:00:00Z",
    url: "/api/v1/incident-photos/ph1?exp=1&sig=a",
  },
] as const;

describe("useIncidents / useIncident", () => {
  beforeEach(() => {
    listMock.mockReset();
    detailMock.mockReset();
    contextMock.mockReset();
    photosMock.mockReset();
    listMock.mockResolvedValue(LIST_PAGE);
    detailMock.mockResolvedValue(DETAIL);
    contextMock.mockResolvedValue(CONTEXT);
    photosMock.mockResolvedValue(PHOTOS);
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
  it("useIncidentContext stores under the tenant-scoped context key (R1.3)", async () => {
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    renderHook(() => useIncidentContext("i1"), { wrapper });
    await waitFor(() => {
      expect(
        client.getQueryData(incidentsKeys.context("tenant-from-session", "i1")),
      ).toEqual(CONTEXT);
    });
    expect(contextMock).toHaveBeenCalledWith("tenant-from-session", "i1");
  });

  it("useIncidentPhotos stores under the tenant-scoped photos key", async () => {
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    renderHook(() => useIncidentPhotos("i1"), { wrapper });
    await waitFor(() => {
      expect(
        client.getQueryData(incidentsKeys.photos("tenant-from-session", "i1")),
      ).toEqual(PHOTOS);
    });
    expect(photosMock).toHaveBeenCalledWith("tenant-from-session", "i1");
  });

  it("useIncidentContext does NOT retry 4xx (retryPolicy wiring)", async () => {
    contextMock.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "not_found", message: "x" }),
    );
    const { result } = renderHook(() => useIncidentContext("i1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(contextMock).toHaveBeenCalledTimes(1);
  });
});
