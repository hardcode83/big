import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUsers } from "./use-users";
import * as dataModule from "../data";

const authMock = vi.fn();
vi.mock("@/lib/auth", () => ({
  useAuth: () => authMock(),
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

const LIST_PAGE = {
  data: [],
  total: 0,
  page: 1,
  perPage: 20,
  totalPages: 0,
};

describe("useUsers", () => {
  beforeEach(() => {
    listMock.mockReset();
    authMock.mockReset();
    authMock.mockReturnValue({ user: { tenant_id: "tenant-from-session" } });
  });

  it("calls the source with the role/status filters it received", async () => {
    listMock.mockResolvedValue(LIST_PAGE);
    const filters = { role: "CLEANER" as const, status: "ACTIVE" as const };
    const { result } = renderHook(() => useUsers(filters), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", filters);
  });

  it("calls the source with page/perPage filters", async () => {
    listMock.mockResolvedValue(LIST_PAGE);
    const filters = { page: 2, perPage: 10 };
    const { result } = renderHook(() => useUsers(filters), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", filters);
  });

  it("throws when there is no authenticated tenant context", () => {
    authMock.mockReturnValue({ user: null });
    expect(() =>
      renderHook(() => useUsers(), { wrapper: freshWrapper() }),
    ).toThrow("Tenant settings requires an authenticated tenant context");
  });

  it("throws when the authenticated user has no tenant_id", () => {
    authMock.mockReturnValue({ user: { tenant_id: null } });
    expect(() =>
      renderHook(() => useUsers(), { wrapper: freshWrapper() }),
    ).toThrow("Tenant settings requires an authenticated tenant context");
  });
});
