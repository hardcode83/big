import { beforeEach, describe, expect, it } from "vitest";

import { useCleaningFiltersStore } from "./use-cleaning-filters-store";

function state() {
  return useCleaningFiltersStore.getState();
}

beforeEach(() => {
  state().reset();
});

describe("useCleaningFiltersStore (R3.4, R3.5)", () => {
  it("opens unfiltered on page 1 (OQ2)", () => {
    expect(state()).toMatchObject({
      propertyId: undefined,
      status: undefined,
      page: 1,
    });
  });

  it.each([
    ["setPropertyId", () => state().setPropertyId("property-7")],
    ["setStatus", () => state().setStatus("CREATED")],
    ["clearPropertyId", () => state().clearPropertyId()],
    ["clearStatus", () => state().clearStatus()],
  ])("%s returns to page 1 from page 3", (_name, act) => {
    state().setPropertyId("property-1");
    state().setStatus("COMPLETED");
    state().setPage(3);
    expect(state().page).toBe(3);

    act();

    expect(state().page).toBe(1);
  });

  it("keeps both filters when only one changes", () => {
    state().setPropertyId("property-1");
    state().setStatus("COMPLETED");

    state().setStatus("CREATED");

    expect(state()).toMatchObject({
      propertyId: "property-1",
      status: "CREATED",
    });
  });

  it("clears each filter independently to undefined", () => {
    state().setPropertyId("property-1");
    state().setStatus("COMPLETED");

    state().clearPropertyId();
    expect(state()).toMatchObject({
      propertyId: undefined,
      status: "COMPLETED",
    });

    state().clearStatus();
    expect(state().status).toBeUndefined();
  });

  it("setPage moves the page and touches neither filter", () => {
    state().setPropertyId("property-1");
    state().setStatus("COMPLETED");

    state().setPage(5);

    expect(state()).toMatchObject({
      propertyId: "property-1",
      status: "COMPLETED",
      page: 5,
    });
  });

  it("reset returns to the unfiltered first page and claims no tenant", () => {
    state().adoptTenant("tenant-1");
    state().setPropertyId("property-1");
    state().setStatus("COMPLETED");
    state().setPage(9);

    state().reset();

    expect(state()).toMatchObject({
      tenantId: undefined,
      propertyId: undefined,
      status: undefined,
      page: 1,
    });
  });
});

describe("adoptTenant — filters belong to one tenant (security.md rule 1)", () => {
  it("discards filters chosen in a different tenant", () => {
    state().adoptTenant("tenant-1");
    state().setPropertyId("property-1");
    state().setStatus("COMPLETED");
    state().setPage(3);

    state().adoptTenant("tenant-2");

    expect(state()).toMatchObject({
      tenantId: "tenant-2",
      propertyId: undefined,
      status: undefined,
      page: 1,
    });
  });

  it("keeps the filters when the tenant is unchanged, so a re-render costs nothing", () => {
    state().adoptTenant("tenant-1");
    state().setPropertyId("property-1");
    state().setPage(4);

    state().adoptTenant("tenant-1");

    expect(state()).toMatchObject({
      tenantId: "tenant-1",
      propertyId: "property-1",
      page: 4,
    });
  });

  it("adopts the first tenant without discarding anything it has not seen", () => {
    state().adoptTenant("tenant-1");
    expect(state().tenantId).toBe("tenant-1");
  });

  it("discards filters when the session ends and no tenant is looking", () => {
    state().adoptTenant("tenant-1");
    state().setPropertyId("property-1");

    state().adoptTenant(undefined);

    expect(state()).toMatchObject({
      tenantId: undefined,
      propertyId: undefined,
      page: 1,
    });
  });
});
