import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { useApprovals, useApprovalsHistory } from "./use-approvals";
import { approvalsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const listMock = vi.fn();
const getApprovalsDataSource = vi.spyOn(dataModule, "getApprovalsDataSource");

getApprovalsDataSource.mockImplementation(
  () =>
    ({
      listApprovals: listMock,
      respond: vi.fn(),
    }) as unknown as ReturnType<typeof dataModule.getApprovalsDataSource>,
);

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retryDelay: 100 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

function row(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "a1",
    relatedType: "INCIDENT",
    status: "PENDING",
    amount: "100.00",
    currency: "EUR",
    requestedAt: "2026-08-12T08:00:00Z",
    respondedAt: null,
    incident: { id: "i1", title: "x", category: "OTHER", severity: "LOW" },
    property: { id: "p1", name: "Piso Sol", internalCode: "MAD-01" },
    ...overrides,
  };
}

describe("useApprovals (R1.1, R1.2, R2.1)", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("calls the source with no status filter — the pending queue", async () => {
    listMock.mockResolvedValue({ items: [row()], total: 1, page: 1, perPage: 20 });
    const { result } = renderHook(() => useApprovals(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(listMock).toHaveBeenCalledWith("tenant-from-session");
  });

  it("stores under the tenant-scoped list key", async () => {
    listMock.mockResolvedValue({ items: [], total: 0, page: 1, perPage: 20 });
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    renderHook(() => useApprovals(), { wrapper });

    await waitFor(() => {
      expect(
        client.getQueryData(approvalsKeys.list("tenant-from-session")),
      ).toBeDefined();
    });
  });
});

describe("useApprovalsHistory (R2.3, design D9)", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("issues one request per answered status, perPage 5 each", async () => {
    listMock.mockResolvedValue({ items: [], total: 0, page: 1, perPage: 5 });
    const { result } = renderHook(() => useApprovalsHistory(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(listMock).toHaveBeenCalledWith("tenant-from-session", {
      status: "APPROVED",
      perPage: 5,
    });
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", {
      status: "REJECTED",
      perPage: 5,
    });
    expect(listMock).toHaveBeenCalledTimes(2);
  });

  it("merges both branches and re-sorts by respondedAt descending", async () => {
    listMock.mockImplementation((_tenantId: string, filters: { status: string }) => {
      if (filters.status === "APPROVED") {
        return Promise.resolve({
          items: [
            row({ id: "approved-newer", status: "APPROVED", respondedAt: "2026-08-15T10:00:00Z" }),
            row({ id: "approved-older", status: "APPROVED", respondedAt: "2026-08-10T10:00:00Z" }),
          ],
          total: 2,
          page: 1,
          perPage: 5,
        });
      }
      return Promise.resolve({
        items: [
          row({ id: "rejected-mid", status: "REJECTED", respondedAt: "2026-08-12T10:00:00Z" }),
        ],
        total: 1,
        page: 1,
        perPage: 5,
      });
    });

    const { result } = renderHook(() => useApprovalsHistory(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(result.current.items.map((item) => item.id)).toEqual([
      "approved-newer",
      "rejected-mid",
      "approved-older",
    ]);
  });

  it("slices to five even when both branches together exceed five", async () => {
    listMock.mockImplementation((_tenantId: string, filters: { status: string }) => {
      const prefix = filters.status === "APPROVED" ? "approved" : "rejected";
      return Promise.resolve({
        items: Array.from({ length: 5 }, (_, index) =>
          row({
            id: `${prefix}-${index}`,
            status: filters.status,
            // Newest first within each branch, disjoint time ranges so the
            // merged order is unambiguous: APPROVED is always newer here.
            respondedAt:
              filters.status === "APPROVED"
                ? `2026-08-2${9 - index}T00:00:00Z`
                : `2026-08-1${9 - index}T00:00:00Z`,
          }),
        ),
        total: 5,
        page: 1,
        perPage: 5,
      });
    });

    const { result } = renderHook(() => useApprovalsHistory(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(result.current.items).toHaveLength(5);
    expect(result.current.items.every((item) => item.status === "APPROVED")).toBe(
      true,
    );
  });

  it("reports isError when either branch fails", async () => {
    listMock.mockImplementation((_tenantId: string, filters: { status: string }) => {
      if (filters.status === "APPROVED") {
        return Promise.reject(
          new ApiError({ code: "NOT_FOUND", message: "boom", status: 404 }),
        );
      }
      return Promise.resolve({ items: [], total: 0, page: 1, perPage: 5 });
    });

    const { result } = renderHook(() => useApprovalsHistory(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(result.current.isError).toBe(true);
    expect(result.current.error).toBeInstanceOf(Error);
  });
});
