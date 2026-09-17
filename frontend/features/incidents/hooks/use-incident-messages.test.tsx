import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { incidentsKeys } from "./query-keys";
import {
  useIncidentMessages,
  useSendIncidentMessage,
} from "./use-incident-messages";

const TENANT = "tenant-from-session";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

const getIncidentMessagesMock = vi.fn();
const sendIncidentMessageMock = vi.fn();

vi.spyOn(dataModule, "getIncidentsDataSource").mockImplementation(
  () =>
    ({
      getIncidentMessages: getIncidentMessagesMock,
      sendIncidentMessage: sendIncidentMessageMock,
    }) as unknown as ReturnType<typeof dataModule.getIncidentsDataSource>,
);

const MESSAGE = {
  id: "message-1",
  authorId: "technician-1",
  authorRole: "TECHNICIAN",
  content: "Ya he llegado",
  createdAt: "2026-08-20T10:00:00Z",
} as const;

const MESSAGE_PAGE = {
  data: [MESSAGE],
  total: 1,
  page: 1,
  perPage: 20,
  totalPages: 1,
};

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
  return { wrapper, invalidated };
}

describe("useIncidentMessages (R2.1, D1, D4)", () => {
  beforeEach(() => {
    getIncidentMessagesMock.mockReset();
    getIncidentMessagesMock.mockResolvedValue(MESSAGE_PAGE);
  });

  it("does not fetch while enabled is false (the messages tab has not been opened yet)", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useIncidentMessages("incident-1", 1, false),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(getIncidentMessagesMock).not.toHaveBeenCalled();
  });

  it("fetches page 1 once enabled, keyed by tenant/incident/page", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useIncidentMessages("incident-1", 1, true),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getIncidentMessagesMock).toHaveBeenCalledWith(
      TENANT,
      "incident-1",
      1,
    );
    expect(result.current.data).toEqual(MESSAGE_PAGE);
  });

  it("a later page uses its own query key (D4 — advancing page never replaces the earlier one)", async () => {
    const { wrapper } = trackedClient();
    const { result } = renderHook(
      () => useIncidentMessages("incident-1", 2, true),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getIncidentMessagesMock).toHaveBeenCalledWith(
      TENANT,
      "incident-1",
      2,
    );
  });
});

describe("useSendIncidentMessage (R2.2, D5)", () => {
  beforeEach(() => {
    sendIncidentMessageMock.mockReset();
    sendIncidentMessageMock.mockResolvedValue(MESSAGE);
  });

  const MESSAGES_PREFIX = [
    ...incidentsKeys.messagesPrefix(TENANT, "incident-1"),
  ];

  it("sends the content and invalidates every cached page on success", async () => {
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useSendIncidentMessage("incident-1"),
      { wrapper },
    );

    result.current.mutate({ content: "Ya he llegado" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sendIncidentMessageMock).toHaveBeenCalledWith(
      TENANT,
      "incident-1",
      "Ya he llegado",
    );
    expect(invalidated).toEqual([MESSAGES_PREFIX]);
  });

  it("also invalidates on failure — never leaves a stale cache behind (D5)", async () => {
    sendIncidentMessageMock.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "nope" }),
    );
    const { wrapper, invalidated } = trackedClient();
    const { result } = renderHook(
      () => useSendIncidentMessage("incident-1"),
      { wrapper },
    );

    result.current.mutate({ content: "" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(sendIncidentMessageMock).toHaveBeenCalledTimes(1);
    expect(invalidated).toEqual([MESSAGES_PREFIX]);
  });

  it("never patches the cache optimistically — no setQueryData call (D5, Rejected)", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const setQueryDataSpy = vi.spyOn(client, "setQueryData");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () => useSendIncidentMessage("incident-1"),
      { wrapper },
    );

    result.current.mutate({ content: "Ya he llegado" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(setQueryDataSpy).not.toHaveBeenCalled();
  });
});
