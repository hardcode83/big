import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUser } from "./use-user";
import * as dataModule from "../data";

const authMock = vi.fn();
vi.mock("@/lib/auth", () => ({
  useAuth: () => authMock(),
}));

const getUserMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      getUser: getUserMock,
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

const USER_PAYLOAD = {
  id: "user-1",
  name: "Ana",
  email: "ana@example.com",
  phone: null,
  preferredLanguage: "es",
  role: "PROPERTY_MANAGER",
  status: "INACTIVE",
  lastLoginAt: null,
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
};

describe("useUser", () => {
  beforeEach(() => {
    getUserMock.mockReset();
    authMock.mockReset();
    authMock.mockReturnValue({ user: { tenant_id: "tenant-from-session" } });
  });

  it("calls the source with the tenant id and the user id, including INACTIVE users", async () => {
    getUserMock.mockResolvedValue(USER_PAYLOAD);
    const { result } = renderHook(() => useUser("user-1"), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getUserMock).toHaveBeenCalledWith("tenant-from-session", "user-1");
    expect(result.current.data?.status).toBe("INACTIVE");
  });

  it("throws when there is no authenticated tenant context", () => {
    authMock.mockReturnValue({ user: null });
    expect(() =>
      renderHook(() => useUser("user-1"), { wrapper: freshWrapper() }),
    ).toThrow("Tenant settings requires an authenticated tenant context");
  });
});
