import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { incidentsKeys } from "./query-keys";
import {
  useAssignIncident,
  useCancelIncident,
  useClassifyIncident,
  useTechnicianDirectory,
  useTriageIncident,
} from "./use-incident-management";

const TENANT = "tenant-from-session";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

const classifyIncidentMock = vi.fn();
const triageIncidentMock = vi.fn();
const assignIncidentMock = vi.fn();
const cancelIncidentMock = vi.fn();
const listTechniciansMock = vi.fn();

vi.spyOn(dataModule, "getIncidentsDataSource").mockImplementation(
  () =>
    ({
      classifyIncident: classifyIncidentMock,
      triageIncident: triageIncidentMock,
      assignIncident: assignIncidentMock,
      cancelIncident: cancelIncidentMock,
      listTechnicians: listTechniciansMock,
    }) as unknown as ReturnType<typeof dataModule.getIncidentsDataSource>,
);

const INCIDENT = { id: "i1", status: "ASSIGNED" } as never;

const TECHNICIANS = [
  { id: "tech-1", name: "Active Tech", isActive: true },
  { id: "tech-2", name: "Inactive Tech", isActive: false },
];

/**
 * The keys touched by one mutation, recorded by spying on the client rather
 * than reading the cache — same harness as `use-incident-cycle.test.tsx` and
 * `use-resolve-incident.test.tsx`: what these tests pin is *which* keys the
 * hook targets (R2.4, R3.4, R4.3, R5.2, R6.1).
 */
function trackedClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidated: unknown[][] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters) => {
    invalidated.push([...((filters?.queryKey ?? []) as unknown[])]);
    return Promise.resolve();
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper, invalidated };
}

const DETAIL_KEY = [...incidentsKeys.detail(TENANT, "i1")];
const CONTEXT_KEY = [...incidentsKeys.context(TENANT, "i1")];
const LIST_PREFIX = [...incidentsKeys.listPrefix(TENANT)];
const BLOCKED_TRANSITIONS_KEY = ["tenant", TENANT, "blocked-transitions"];
const DASHBOARD_CARDS_KEY = ["tenant", TENANT, "dashboard-cards"];
const PROPERTY_TIMELINE_KEY = ["tenant", TENANT, "property-timeline"];

beforeEach(() => {
  for (const mock of [
    classifyIncidentMock,
    triageIncidentMock,
    assignIncidentMock,
    cancelIncidentMock,
  ]) {
    mock.mockReset();
    mock.mockResolvedValue(INCIDENT);
  }
  listTechniciansMock.mockReset().mockResolvedValue(TECHNICIANS);
});

describe("useTechnicianDirectory (R2.1)", () => {
  it("exposes the roster unfiltered by isActive", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(() => useTechnicianDirectory(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(listTechniciansMock).toHaveBeenCalledWith(TENANT);
    expect(result.current.data).toEqual(TECHNICIANS);
    expect(result.current.data).toEqual(
      expect.arrayContaining([expect.objectContaining({ isActive: false })]),
    );
  });
});

describe("useClassifyIncident (R4.1, R4.3)", () => {
  it("classifies with no body and invalidates detail, context and the list prefix", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useClassifyIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(classifyIncidentMock).toHaveBeenCalledWith(TENANT, "i1");
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });

  it("a 409 still invalidates in onSettled and does not retry (R6.1)", async () => {
    classifyIncidentMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useClassifyIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(classifyIncidentMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });
});

describe("useTriageIncident (R3.2, R3.4/D8)", () => {
  it("flattens the variables into the input and invalidates the three common keys", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useTriageIncident(), { wrapper });

    result.current.mutate({
      incidentId: "i1",
      category: "PLUMBING",
      severity: "HIGH",
      estimatedCost: "45.00",
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(triageIncidentMock).toHaveBeenCalledWith(TENANT, "i1", {
      category: "PLUMBING",
      severity: "HIGH",
      estimatedCost: "45.00",
    });
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });

  it("a 409 still invalidates in onSettled (R6.1)", async () => {
    triageIncidentMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useTriageIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1", severity: "LOW" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(triageIncidentMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });
});

describe("useAssignIncident (R2.1, R2.4)", () => {
  it("flattens the variables into the input and invalidates the three common keys", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useAssignIncident(), { wrapper });

    result.current.mutate({
      incidentId: "i1",
      technicianId: "tech-1",
      assignmentNote: "Bring spare part",
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(assignIncidentMock).toHaveBeenCalledWith(TENANT, "i1", {
      technicianId: "tech-1",
      assignmentNote: "Bring spare part",
    });
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });

  it("a 409 still invalidates in onSettled (R6.1)", async () => {
    assignIncidentMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useAssignIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1", technicianId: "tech-1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(assignIncidentMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });
});

describe("useCancelIncident (R5.1, R5.2, R5.3)", () => {
  it("cancels with no body and invalidates the three common keys plus the dashboard buckets", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useCancelIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(cancelIncidentMock).toHaveBeenCalledWith(TENANT, "i1");
    expect(invalidated).toEqual(
      expect.arrayContaining([
        DETAIL_KEY,
        CONTEXT_KEY,
        LIST_PREFIX,
        BLOCKED_TRANSITIONS_KEY,
        DASHBOARD_CARDS_KEY,
        PROPERTY_TIMELINE_KEY,
      ]),
    );
    expect(invalidated).toHaveLength(6);
  });

  it("a 409 still invalidates all six keys in onSettled (R6.1)", async () => {
    cancelIncidentMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useCancelIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(cancelIncidentMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual(
      expect.arrayContaining([
        DETAIL_KEY,
        CONTEXT_KEY,
        LIST_PREFIX,
        BLOCKED_TRANSITIONS_KEY,
        DASHBOARD_CARDS_KEY,
        PROPERTY_TIMELINE_KEY,
      ]),
    );
    expect(invalidated).toHaveLength(6);
  });
});
