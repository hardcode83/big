import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { HttpApprovalsSource } from "../data/http/http-approvals-source";
import { useRespondOwnerApproval } from "./use-respond-approval";
import { approvalsKeys } from "./query-keys";

const respond = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("../data", () => ({
  getApprovalsDataSource: () =>
    ({
      listApprovals: vi.fn(),
      respond,
    }) as unknown as HttpApprovalsSource,
}));

function harness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, invalidate, Wrapper };
}

beforeEach(() => {
  respond.mockReset().mockResolvedValue(undefined);
});

describe("useRespondOwnerApproval (R3.3, design D10)", () => {
  it("forwards the input verbatim to the source", async () => {
    const { Wrapper } = harness();
    const { result } = renderHook(() => useRespondOwnerApproval(), {
      wrapper: Wrapper,
    });

    result.current.mutate({
      approvalId: "a1",
      status: "APPROVED",
      responseNotes: "Adelante",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(respond).toHaveBeenCalledWith("tenant-1", {
      approvalId: "a1",
      status: "APPROVED",
      responseNotes: "Adelante",
    });
    expect(respond).toHaveBeenCalledTimes(1);
  });

  it("invalidates approvalsKeys.listPrefix(tenantId) on success (R3.3)", async () => {
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useRespondOwnerApproval(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ approvalId: "a1", status: "REJECTED" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: approvalsKeys.listPrefix("tenant-1"),
    });
  });

  it("invalidates approvalsKeys.listPrefix(tenantId) on a 409 too (R3.4) — the stale row leaves the screen", async () => {
    respond.mockRejectedValueOnce(
      new ApiError({ code: "CONFLICT", message: "already answered", status: 409 }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useRespondOwnerApproval(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ approvalId: "a1", status: "APPROVED" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: approvalsKeys.listPrefix("tenant-1"),
    });
  });

  it("does not invalidate on a non-409 failure — the row is not known stale", async () => {
    respond.mockRejectedValueOnce(
      new ApiError({ code: "FORBIDDEN", message: "not allowed", status: 403 }),
    );
    const { invalidate, Wrapper } = harness();
    const { result } = renderHook(() => useRespondOwnerApproval(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ approvalId: "a1", status: "APPROVED" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(invalidate).not.toHaveBeenCalled();
  });

  it("never retries a rejected write", async () => {
    respond.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "already answered", status: 409 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(() => useRespondOwnerApproval(), {
      wrapper: Wrapper,
    });

    result.current.mutate({ approvalId: "a1", status: "APPROVED" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(respond).toHaveBeenCalledTimes(1);
  });

  it("does not invalidate another tenant's entries", async () => {
    const { client, Wrapper } = harness();
    const otherTenantKey = approvalsKeys.list("tenant-2");
    client.setQueryData(otherTenantKey, {
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
    });

    const { result } = renderHook(() => useRespondOwnerApproval(), {
      wrapper: Wrapper,
    });
    result.current.mutate({ approvalId: "a1", status: "APPROVED" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(otherTenantKey)?.isInvalidated).toBe(false);
  });
});
