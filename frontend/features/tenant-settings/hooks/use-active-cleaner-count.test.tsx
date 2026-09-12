import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useActiveCleanerCount } from "./use-active-cleaner-count";
import * as dataModule from "../data";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const listMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      listUsers: listMock,
    }) as unknown as ReturnType<typeof dataModule.getTenantSettingsDataSource>,
);

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useActiveCleanerCount", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("is disabled until explicitly enabled: does not fire when enabled is false", () => {
    const { result } = renderHook(() => useActiveCleanerCount(false), {
      wrapper: freshWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(listMock).not.toHaveBeenCalled();
  });

  it("fires GET with role=CLEANER, status=ACTIVE, per_page=1 and exposes total when enabled", async () => {
    listMock.mockResolvedValue({ data: [{}], total: 1, page: 1, perPage: 1, totalPages: 1 });
    const { result } = renderHook(() => useActiveCleanerCount(true), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", {
      role: "CLEANER",
      status: "ACTIVE",
      perPage: 1,
    });
    expect(result.current.data).toBe(1);
  });
});
