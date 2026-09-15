import { describe, expect, it, vi } from "vitest";

const { createAuthenticatedClients, notifySessionExpired } =
  vi.hoisted(() => {
    const client = { request: vi.fn(), requestBinary: vi.fn() };
    return {
      apiClient: client,
      createAuthenticatedClients: vi.fn(() => ({
        apiClient: client,
        refreshTokens: vi.fn(),
      })),
      notifySessionExpired: vi.fn(),
    };
  });

vi.mock("@/lib/api/authenticated-client", () => ({
  createAuthenticatedClients,
  notifySessionExpired,
}));

import {
  getStatementsDataSource,
  type OwnerStatementFilters,
} from "./index";
import { HttpStatementsSource } from "./http/http-statements-source";

describe("statements data composition", () => {
  it("creates one authenticated HTTP source with shared session expiry", () => {
    expect(createAuthenticatedClients).toHaveBeenCalledTimes(1);
    expect(createAuthenticatedClients).toHaveBeenCalledWith({
      apiBaseUrl: "",
      onSessionExpired: notifySessionExpired,
    });
    expect(getStatementsDataSource()).toBeInstanceOf(HttpStatementsSource);
    expect(getStatementsDataSource()).toBe(getStatementsDataSource());
  });

  it("does not admit tenant identity as a statement filter", () => {
    const filters: OwnerStatementFilters = { propertyId: "property-1" };
    expect(filters).toEqual({ propertyId: "property-1" });

    if (false) {
      const invalid: OwnerStatementFilters = {
        // @ts-expect-error Tenant identity comes from auth, never UI filters.
        tenantId: "tenant-1",
      };
      void invalid;
    }
  });
});
