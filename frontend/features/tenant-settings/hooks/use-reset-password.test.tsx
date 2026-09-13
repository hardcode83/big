import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useResetPassword } from "./use-reset-password";
import * as dataModule from "../data";
import { tenantSettingsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const resetPasswordMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      resetPassword: resetPasswordMock,
    }) as unknown as ReturnType<typeof dataModule.getTenantSettingsDataSource>,
);

const RESET = {
  user: {
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
  },
  temporaryPassword: "one-time-secret",
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useResetPassword", () => {
  beforeEach(() => {
    resetPasswordMock.mockReset();
  });

  it("calls the source with the user id", async () => {
    resetPasswordMock.mockResolvedValue(RESET);
    const client = makeClient();
    const { result } = renderHook(() => useResetPassword(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate("user-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(resetPasswordMock).toHaveBeenCalledWith("tenant-from-session", "user-1");
  });

  it("has gcTime: 0 so the temporary password does not linger in the mutation cache", async () => {
    resetPasswordMock.mockResolvedValue(RESET);
    const client = makeClient();
    const { result } = renderHook(() => useResetPassword(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate("user-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const [mutation] = client.getMutationCache().getAll();
    expect(mutation?.options.gcTime).toBe(0);
  });

  it("invalidates usersList on success", async () => {
    resetPasswordMock.mockResolvedValue(RESET);
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useResetPassword(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate("user-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: tenantSettingsKeys.usersList("tenant-from-session"),
    });
  });
});
