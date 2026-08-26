import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  useSelectedTimelineProperty,
  useTimelinePropertyStore,
} from "./use-timeline-property-store";

/**
 * R1.4 forbids persisting the chosen property anywhere the browser keeps beyond
 * memory, because a `property_id` identifies a tenant's asset and none of those
 * stores is scoped by tenant.
 *
 * The negative is asserted two independent ways, on purpose. The spy proves no
 * write was *attempted*, and the key snapshots prove nothing *landed* — which holds
 * whatever backs Storage under jsdom. A test that cannot fail is worse than no
 * test, and both reviewers of this file disputed the spy in opposite directions, so
 * it is pinned by something that does not depend on spy mechanics at all.
 *
 * One spy, not two: under this jsdom, `localStorage` and `sessionStorage` share
 * `Storage.prototype.setItem`, so patching the prototype covers both. Spying the
 * `sessionStorage` INSTANCE as well looks like a second check but is not — vitest
 * returns the already-installed prototype mock, so it is the same mock under
 * another name, and on its own (without the prototype spy) it records nothing and
 * writes a phantom `setItem` entry into the store. Raised by the security panel.
 */
let setItem: ReturnType<typeof vi.spyOn>;
let cookieWrites: string[];

beforeEach(() => {
  useTimelinePropertyStore.getState().clear();
  localStorage.clear();
  sessionStorage.clear();
  setItem = vi.spyOn(Storage.prototype, "setItem");
  cookieWrites = [];
  vi.spyOn(document, "cookie", "set").mockImplementation((value: string) => {
    cookieWrites.push(value);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useTimelinePropertyStore (R1.4)", () => {
  it("starts with no selection", () => {
    expect(useTimelinePropertyStore.getState().tenantId).toBeUndefined();
    expect(useTimelinePropertyStore.getState().propertyId).toBeUndefined();
  });

  it("keeps the tenant/property pair across reads", () => {
    useTimelinePropertyStore.getState().select("tenant-1", "redes11");

    expect(useTimelinePropertyStore.getState()).toMatchObject({
      tenantId: "tenant-1",
      propertyId: "redes11",
    });
    // A second read sees the same pair — the selection survives navigation away
    // and back, which is what R1.4 conserves.
    expect(useTimelinePropertyStore.getState().propertyId).toBe("redes11");
  });

  it("never writes to localStorage, sessionStorage or a cookie", () => {
    useTimelinePropertyStore.getState().select("tenant-1", "redes11");
    useTimelinePropertyStore.getState().select("tenant-2", "pajaritos8");
    useTimelinePropertyStore.getState().clear();

    // Covers both storages: they share the prototype method.
    expect(setItem).not.toHaveBeenCalled();
    expect(cookieWrites).toEqual([]);
    // Independent of the spies: nothing landed in either store.
    expect(Object.keys(localStorage)).toEqual([]);
    expect(Object.keys(sessionStorage)).toEqual([]);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("clear drops both halves of the pair", () => {
    useTimelinePropertyStore.getState().select("tenant-1", "redes11");
    useTimelinePropertyStore.getState().clear();

    expect(useTimelinePropertyStore.getState()).toMatchObject({
      tenantId: undefined,
      propertyId: undefined,
    });
  });
});

/**
 * The isolation test security.md rule 1 requires of a new module that carries a
 * tenant identifier: a selection made by one tenant must not be readable as the
 * next tenant's, because `logout` clears the session but not this store
 * (`lib/auth/auth-provider.tsx`), so the pair outlives the tenant that made it.
 */
describe("useSelectedTimelineProperty — tenant isolation (R1.4, D3)", () => {
  it("returns the selection to the tenant that made it", () => {
    useTimelinePropertyStore.getState().select("tenant-1", "redes11");

    const { result } = renderHook(() => useSelectedTimelineProperty("tenant-1"));
    expect(result.current).toBe("redes11");
  });

  it("hides a selection made by another tenant", () => {
    useTimelinePropertyStore.getState().select("tenant-1", "redes11");

    // Same tab, same store, different tenant: the stale pair reads as "none".
    const { result } = renderHook(() => useSelectedTimelineProperty("tenant-2"));
    expect(result.current).toBeUndefined();
  });

  it("returns nothing when no selection was made", () => {
    const { result } = renderHook(() => useSelectedTimelineProperty("tenant-1"));
    expect(result.current).toBeUndefined();
  });
});
