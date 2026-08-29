import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { incidentsKeys } from "./query-keys";
import {
  useIncidentCycleAction,
  useResolveIncident,
  useUploadIncidentPhoto,
} from "./use-incident-cycle";

const TENANT = "tenant-from-session";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

// No `next/navigation` mock any more: the hook does not navigate. Where a
// successful `reject` goes is the caller's decision, passed in as `onRejected`
// (design D1) — this suite asserts the callback fires, not a route.
const onRejected = vi.fn();

const acceptMock = vi.fn();
const rejectMock = vi.fn();
const enRouteMock = vi.fn();
const waitPartsMock = vi.fn();
const resumeMock = vi.fn();
const resolveMock = vi.fn();
const uploadPhotoMock = vi.fn();

vi.spyOn(dataModule, "getIncidentsDataSource").mockImplementation(
  () =>
    ({
      accept: acceptMock,
      reject: rejectMock,
      enRoute: enRouteMock,
      waitParts: waitPartsMock,
      resume: resumeMock,
      resolve: resolveMock,
      uploadPhoto: uploadPhotoMock,
    }) as unknown as ReturnType<typeof dataModule.getIncidentsDataSource>,
);

const INCIDENT = { id: "i1", status: "ACCEPTED" } as never;
const PHOTO = { id: "ph1", stage: "BEFORE" } as never;

/**
 * The keys touched by one mutation, recorded by spying on the client rather
 * than by reading the cache: what these tests pin is *which* keys the hook
 * targets, which is what R3.6/R5.5 constrain.
 */
function trackedClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidated: unknown[][] = [];
  const removed: unknown[][] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation((filters) => {
    invalidated.push([...((filters?.queryKey ?? []) as unknown[])]);
    return Promise.resolve();
  });
  vi.spyOn(client, "removeQueries").mockImplementation((filters) => {
    removed.push([...((filters?.queryKey ?? []) as unknown[])]);
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { wrapper, invalidated, removed };
}

const DETAIL_KEY = [...incidentsKeys.detail(TENANT, "i1")];
const CONTEXT_KEY = [...incidentsKeys.context(TENANT, "i1")];
const LIST_PREFIX = [...incidentsKeys.listPrefix(TENANT)];
const PHOTOS_KEY = [...incidentsKeys.photos(TENANT, "i1")];

describe("useIncidentCycleAction (D8)", () => {
  beforeEach(() => {
    onRejected.mockReset();
    for (const mock of [
      acceptMock,
      rejectMock,
      enRouteMock,
      waitPartsMock,
      resumeMock,
      resolveMock,
      uploadPhotoMock,
    ]) {
      mock.mockReset();
      mock.mockResolvedValue(INCIDENT);
    }
    uploadPhotoMock.mockResolvedValue(PHOTO);
  });

  it.each([
    ["accept", acceptMock],
    ["en-route", enRouteMock],
    ["wait-parts", waitPartsMock],
    ["resume", resumeMock],
  ] as const)(
    "%s invalidates detail, context and the list prefix, and nothing else",
    async (action, mock) => {
      const { wrapper, invalidated, removed } = trackedClient();
      const { result } = renderHook(() => useIncidentCycleAction({ onRejected }), { wrapper });

      result.current.mutate({ incidentId: "i1", action });

      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(mock).toHaveBeenCalledOnce();
      expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
      expect(removed).toEqual([]);
      expect(onRejected).not.toHaveBeenCalled();
    },
  );

  it("passes the ETA through for accept and omits it when absent", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(() => useIncidentCycleAction({ onRejected }), { wrapper });

    result.current.mutate({
      incidentId: "i1",
      action: "accept",
      etaAt: "2026-08-12T18:30:00.000Z",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(acceptMock).toHaveBeenCalledWith(
      TENANT,
      "i1",
      "2026-08-12T18:30:00.000Z",
    );
  });

  it("a 409 still invalidates (the onSettled branch) and does not retry (R3.7)", async () => {
    acceptMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useIncidentCycleAction({ onRejected }), { wrapper });

    result.current.mutate({ incidentId: "i1", action: "accept" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(acceptMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
  });

  it("reject removes detail and context, invalidates the list and calls onRejected (R3.5)", async () => {
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(() => useIncidentCycleAction({ onRejected }), { wrapper });

    result.current.mutate({ incidentId: "i1", action: "reject" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(removed).toEqual([DETAIL_KEY, CONTEXT_KEY]);
    expect(invalidated).toEqual([LIST_PREFIX]);
    expect(onRejected).toHaveBeenCalledOnce();
  });

  it("a reject that fails leaves the incident in place and refreshes it", async () => {
    rejectMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "nope" }),
    );
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(() => useIncidentCycleAction({ onRejected }), { wrapper });

    result.current.mutate({ incidentId: "i1", action: "reject" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(removed).toEqual([]);
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
    expect(onRejected).not.toHaveBeenCalled();
  });
});

describe("useResolveIncident (R4.1, D12)", () => {
  beforeEach(() => {
    resolveMock.mockReset();
    resolveMock.mockResolvedValue(INCIDENT);
  });

  it("invalidates detail, context and the list prefix", async () => {
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(() => useResolveIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1", finalCost: "120.50" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(resolveMock).toHaveBeenCalledWith(TENANT, "i1", {
      finalCost: "120.50",
    });
    expect(invalidated).toEqual([DETAIL_KEY, CONTEXT_KEY, LIST_PREFIX]);
    expect(removed).toEqual([]);
  });

  it("does not retry a 422", async () => {
    resolveMock.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "x" }),
    );
    const { wrapper } = trackedClient();
    const { result } = renderHook(() => useResolveIncident(), { wrapper });

    result.current.mutate({ incidentId: "i1", finalCost: "-1" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(resolveMock).toHaveBeenCalledTimes(1);
  });
});

describe("useUploadIncidentPhoto (R5.5)", () => {
  beforeEach(() => {
    uploadPhotoMock.mockReset();
    uploadPhotoMock.mockResolvedValue(PHOTO);
  });

  it("invalidates only the photo list of that incident", async () => {
    const { wrapper, invalidated, removed } = trackedClient();
    const { result } = renderHook(() => useUploadIncidentPhoto(), { wrapper });
    const file = new File(["bytes"], "before.jpg", { type: "image/jpeg" });

    result.current.mutate({ incidentId: "i1", file, stage: "BEFORE" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(uploadPhotoMock).toHaveBeenCalledWith(TENANT, "i1", file, "BEFORE");
    expect(invalidated).toEqual([PHOTOS_KEY]);
    expect(removed).toEqual([]);
  });

  /**
   * A 409 means the status this client believes is stale — the incident was
   * closed or sent to the owner while the technician was choosing a file. The
   * message R5.6 requires is derived from the **refreshed** status (D7), so the
   * detail has to be invalidated too; without this the only reachable reason is
   * `out-of-order` and the other two messages are dead strings.
   */
  it("a 409 also refreshes the incident, so the reason can be read (R5.6, D7)", async () => {
    uploadPhotoMock.mockRejectedValue(
      new ApiError({ status: 409, code: "CONFLICT", message: "x" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useUploadIncidentPhoto(), { wrapper });

    result.current.mutate({
      incidentId: "i1",
      file: new File(["b"], "a.jpg"),
      stage: "AFTER",
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidated).toEqual([PHOTOS_KEY, DETAIL_KEY]);
    expect(uploadPhotoMock).toHaveBeenCalledTimes(1);
  });

  it("a 413 leaves the incident alone — only the photo list is touched", async () => {
    uploadPhotoMock.mockRejectedValue(
      new ApiError({ status: 413, code: "PAYLOAD_TOO_LARGE", message: "x" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(() => useUploadIncidentPhoto(), { wrapper });

    result.current.mutate({
      incidentId: "i1",
      file: new File(["b"], "a.jpg"),
      stage: "AFTER",
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidated).toEqual([PHOTOS_KEY]);
  });

  it("does not retry a 502", async () => {
    uploadPhotoMock.mockRejectedValue(
      new ApiError({ status: 502, code: "STORAGE_UNAVAILABLE", message: "x" }),
    );
    const { wrapper } = trackedClient();
    const { result } = renderHook(() => useUploadIncidentPhoto(), { wrapper });

    result.current.mutate({
      incidentId: "i1",
      file: new File(["b"], "a.jpg"),
      stage: "AFTER",
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(uploadPhotoMock).toHaveBeenCalledTimes(1);
  });
});
