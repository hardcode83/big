import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUpdateUser } from "./use-update-user";
import * as dataModule from "../data";
import { tenantSettingsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const updateUserMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      updateUser: updateUserMock,
    }) as unknown as ReturnType<typeof dataModule.getTenantSettingsDataSource>,
);

const UPDATED = {
  id: "user-1",
  name: "Ana",
  email: "ana@example.com",
  phone: null,
  preferredLanguage: "es",
  role: "PROPERTY_MANAGER",
  status: "ACTIVE",
  lastLoginAt: null,
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useUpdateUser", () => {
  beforeEach(() => {
    updateUserMock.mockReset();
  });

  it("sends only the changed fields it received to the source", async () => {
    updateUserMock.mockResolvedValue(UPDATED);
    const client = makeClient();
    const { result } = renderHook(() => useUpdateUser(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate({ userId: "user-1", input: { role: "PROPERTY_MANAGER" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(updateUserMock).toHaveBeenCalledWith("tenant-from-session", "user-1", {
      role: "PROPERTY_MANAGER",
    });
  });

  it("supports reactivation via {status: 'ACTIVE'} (design D7)", async () => {
    updateUserMock.mockResolvedValue(UPDATED);
    const client = makeClient();
    const { result } = renderHook(() => useUpdateUser(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate({ userId: "user-1", input: { status: "ACTIVE" } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(updateUserMock).toHaveBeenCalledWith("tenant-from-session", "user-1", {
      status: "ACTIVE",
    });
  });

  it("invalidates usersList and the row's userDetail on success", async () => {
    updateUserMock.mockResolvedValue(UPDATED);
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useUpdateUser(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate({ userId: "user-1", input: { name: "Ana B." } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: tenantSettingsKeys.usersList("tenant-from-session"),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: tenantSettingsKeys.userDetail("tenant-from-session", "user-1"),
    });
  });
});
