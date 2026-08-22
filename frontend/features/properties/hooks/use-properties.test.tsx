import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import * as dataModule from "../data";
import { normalizePropertyFilters, propertiesKeys } from "./query-keys";
import { useProperties } from "./use-properties";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const listMock = vi.fn();
const getPropertiesDataSource = vi.spyOn(dataModule, "getPropertiesDataSource");

getPropertiesDataSource.mockImplementation(
  () =>
    ({ listProperties: listMock }) as unknown as ReturnType<
      typeof dataModule.getPropertiesDataSource
    >,
);

/**
 * A wrapper that does NOT override the QueryClient-level retry.
 *
 * This matters and is copied deliberately from
 * `features/reservations/hooks/use-reservations.test.tsx`, which documents the
 * trap: a wrapper setting `defaultOptions.queries.retry = false` MASKS the
 * hook's own retry config, so deleting `retry: retryPolicy` from the hook would
 * leave the test green. Without the override, the hook's policy is the one
 * TanStack Query consults, which is what the 4xx test below actually proves.
 */
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

const LIST_PAGE = {
  data: [],
  page: 1,
  perPage: 20,
  total: 0,
  totalPages: 0,
};

beforeEach(() => {
  listMock.mockReset();
  listMock.mockResolvedValue(LIST_PAGE);
});

describe("useProperties — tenant-scoped query key (R1, design D6)", () => {
  it("scopes the key to the tenant from the session", () => {
    const key = propertiesKeys.list("tenant-from-session", {});
    expect(key[0]).toBe("tenant");
    expect(key[1]).toBe("tenant-from-session");
    expect(key[2]).toBe("properties-list");
  });

  it("gives two tenants two different keys, for the same filters", () => {
    // Rule 1 of `steering/security.md` asks every new module for its own
    // tenant-isolation test. The guarantee is structural in `tenantScopedKey`,
    // but the rule wants it asserted per module, not inherited: raised by the
    // tenancy reviewer in /sdd:review.
    const a = propertiesKeys.list("tenant-a", { status: "ACTIVE" });
    const b = propertiesKeys.list("tenant-b", { status: "ACTIVE" });
    expect(a).not.toEqual(b);
    expect(a[1]).toBe("tenant-a");
    expect(b[1]).toBe("tenant-b");
    // And no key can be built that would be shared across tenants.
    expect(JSON.stringify(a)).not.toContain("tenant-b");
  });

  it("refuses to build a key without a tenant", () => {
    // `tenantScopedKey` throws rather than writing a global cache entry, so a
    // cross-tenant key cannot be produced by accident.
    expect(() => propertiesKeys.list("", {})).toThrow();
  });

  it("passes the tenant from the session to the data source, not from an argument", async () => {
    const { result } = renderHook(() => useProperties(), {
      wrapper: freshWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listMock).toHaveBeenCalledWith("tenant-from-session", {});
  });
});

describe("useProperties — key stability across equivalent renders (R2.3)", () => {
  it("produces the same key regardless of the order the filters were built in", () => {
    const a = propertiesKeys.list("t", {
      status: "ACTIVE",
      page: 2,
      currentOperationalState: "VACANT_READY",
    });
    const b = propertiesKeys.list("t", {
      currentOperationalState: "VACANT_READY",
      page: 2,
      status: "ACTIVE",
    });
    expect(a).toEqual(b);
    // Structural equality is what TanStack Query hashes, so this is the
    // property that stops an equivalent re-render from refetching.
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("omits a filter set to all instead of sending it as undefined", () => {
    expect(normalizePropertyFilters({ status: undefined, page: 1 })).toEqual({
      page: 1,
    });
    expect(Object.keys(normalizePropertyFilters({ status: undefined }))).toEqual(
      ["page"],
    );
  });

  it("treats 'no page' and 'page 1' as the same cache entry", () => {
    // Raised by the QA panel: the backend defaults `page` to 1, so a caller
    // doing `useProperties()` to mean "the first page" must not populate an
    // entry separate from the one the list renders — neither would invalidate
    // the other.
    expect(propertiesKeys.list("t", {})).toEqual(
      propertiesKeys.list("t", { page: 1 }),
    );
    expect(propertiesKeys.list("t", { status: "ACTIVE" })).toEqual(
      propertiesKeys.list("t", { status: "ACTIVE", page: 1 }),
    );
    // And a different page is still a different entry.
    expect(propertiesKeys.list("t", {})).not.toEqual(
      propertiesKeys.list("t", { page: 2 }),
    );
  });

  it("distinguishes no-filter from a filtered request", () => {
    const unfiltered = propertiesKeys.list("t", {});
    const filtered = propertiesKeys.list("t", { status: "INACTIVE" });
    expect(unfiltered).not.toEqual(filtered);
  });
});

describe("useProperties — retry policy (R3.7)", () => {
  it("does not retry a 4xx", async () => {
    listMock.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );

    const { result } = renderHook(() => useProperties(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    // One attempt only: the shared `retryPolicy` returns false for 4xx.
    expect(listMock).toHaveBeenCalledTimes(1);
  });

  it("retries a 5xx before giving up", async () => {
    listMock.mockRejectedValue(
      new ApiError({ code: "BOOM", message: "boom", status: 500 }),
    );

    const { result } = renderHook(() => useProperties(), {
      wrapper: freshWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true), {
      timeout: 5000,
    });
    // The shared policy allows `failureCount < 2`, so more than one attempt.
    expect(listMock.mock.calls.length).toBeGreaterThan(1);
  });
});
