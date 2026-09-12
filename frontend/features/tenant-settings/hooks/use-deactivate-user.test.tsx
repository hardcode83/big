import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDeactivateUser } from "./use-deactivate-user";
import * as dataModule from "../data";
import { tenantSettingsKeys } from "./query-keys";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const deactivateUserMock = vi.fn();
const getTenantSettingsDataSource = vi.spyOn(dataModule, "getTenantSettingsDataSource");
getTenantSettingsDataSource.mockImplementation(
  () =>
    ({
      deactivateUser: deactivateUserMock,
    }) as unknown as ReturnType<typeof dataModule.getTenantSettingsDataSource>,
);

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useDeactivateUser", () => {
  beforeEach(() => {
    deactivateUserMock.mockReset();
  });

  it("calls DELETE via the source with the tenant id and user id", async () => {
    deactivateUserMock.mockResolvedValue(undefined);
    const client = makeClient();
    const { result } = renderHook(() => useDeactivateUser(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate("user-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(deactivateUserMock).toHaveBeenCalledWith("tenant-from-session", "user-1");
  });

  it("invalidates usersList and the row's userDetail on success", async () => {
    deactivateUserMock.mockResolvedValue(undefined);
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useDeactivateUser(), {
      wrapper: wrapperFor(client),
    });
    result.current.mutate("user-1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: tenantSettingsKeys.usersList("tenant-from-session"),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: tenantSettingsKeys.userDetail("tenant-from-session", "user-1"),
    });
  });
});
