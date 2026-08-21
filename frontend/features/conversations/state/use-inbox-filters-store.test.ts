import { beforeEach, describe, expect, it } from "vitest";

import { useInboxFiltersStore } from "./use-inbox-filters-store";

beforeEach(() => {
  useInboxFiltersStore.getState().reset();
});

describe("useInboxFiltersStore (task 4.1, D6, R2.5)", () => {
  it("starts with no filter selected on page 1", () => {
    expect(useInboxFiltersStore.getState()).toMatchObject({
      status: undefined,
      escalationStatus: undefined,
      propertyId: undefined,
      page: 1,
    });
  });

  it("resets the page to 1 whenever any filter changes", () => {
    const store = useInboxFiltersStore;
    for (const change of [
      () => store.getState().setStatus("ESCALATED"),
      () => store.getState().setEscalationStatus("PENDING_HUMAN"),
      () => store.getState().setPropertyId("property-1"),
      () => store.getState().setStatus(undefined),
    ]) {
      store.getState().setPage(4);
      expect(store.getState().page).toBe(4);
      change();
      expect(store.getState().page).toBe(1);
    }
  });

  it("changes the page without touching the filters", () => {
    const store = useInboxFiltersStore;
    store.getState().setStatus("OPEN");
    store.getState().setPropertyId("property-1");
    store.getState().setPage(3);

    expect(store.getState()).toMatchObject({
      status: "OPEN",
      propertyId: "property-1",
      page: 3,
    });
  });

  it("stores no server state — no conversations and no messages", () => {
    useInboxFiltersStore.getState().setStatus("OPEN");
    const dataKeys = Object.entries(useInboxFiltersStore.getState())
      .filter(([, value]) => typeof value !== "function")
      .map(([key]) => key);

    expect(dataKeys.sort()).toEqual([
      "escalationStatus",
      "page",
      "propertyId",
      "status",
    ]);
  });
});
