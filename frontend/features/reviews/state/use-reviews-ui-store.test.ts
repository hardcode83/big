import { describe, expect, it } from "vitest";

import { useReviewsUiStore } from "./use-reviews-ui-store";

/**
 * Pins the invariants of D14:
 *
 *  - reset to page 1 lives inside every filter setter;
 *  - the two slices do not share filters or page;
 *  - switching tabs closes the detail;
 *  - `adoptTenant` with another tenant wipes everything.
 */
describe("useReviewsUiStore", () => {
  it("starts on the Borradores tab with both slices at page 1", () => {
    const state = useReviewsUiStore.getState();
    expect(state.activeTab).toBe("drafts");
    expect(state.detailReviewId).toBeNull();
    expect(state.drafts.page).toBe(1);
    expect(state.reviews.page).toBe(1);
  });

  it("drafts filter setters reset page to 1", () => {
    const store = useReviewsUiStore.getState();
    store.setDraftsPage(3);
    expect(useReviewsUiStore.getState().drafts.page).toBe(3);
    store.setDraftsPropertyId("p1");
    const next = useReviewsUiStore.getState().drafts;
    expect(next.propertyId).toBe("p1");
    expect(next.page).toBe(1);
  });

  it("reviews filter setters reset page to 1", () => {
    const store = useReviewsUiStore.getState();
    store.setReviewsPage(2);
    store.setReviewsStatus("APPROVED");
    const next = useReviewsUiStore.getState().reviews;
    expect(next.status).toBe("APPROVED");
    expect(next.page).toBe(1);
  });

  it("the two slices do not share propertyId or page", () => {
    const store = useReviewsUiStore.getState();
    store.setDraftsPropertyId("p1");
    store.setDraftsPage(5);
    expect(useReviewsUiStore.getState().reviews.propertyId).toBeUndefined();
    expect(useReviewsUiStore.getState().reviews.page).toBe(1);
  });

  it("setActiveTab closes any open detail", () => {
    const store = useReviewsUiStore.getState();
    store.setDetailReviewId("r1");
    expect(useReviewsUiStore.getState().detailReviewId).toBe("r1");
    store.setActiveTab("reviews");
    expect(useReviewsUiStore.getState().detailReviewId).toBeNull();
    expect(useReviewsUiStore.getState().activeTab).toBe("reviews");
  });

  it("setActiveTab does not touch any slice", () => {
    const store = useReviewsUiStore.getState();
    store.setDraftsPropertyId("p1");
    store.setReviewsPropertyId("p2");
    store.setActiveTab("reviews");
    expect(useReviewsUiStore.getState().drafts.propertyId).toBe("p1");
    expect(useReviewsUiStore.getState().reviews.propertyId).toBe("p2");
  });

  it("adoptTenant wipes all filters when the tenant changes", () => {
    const store = useReviewsUiStore.getState();
    store.adoptTenant("tenant-A");
    store.setDraftsPropertyId("p1");
    store.setReviewsStatus("APPROVED");
    store.setDetailReviewId("r9");
    store.adoptTenant("tenant-B");
    const next = useReviewsUiStore.getState();
    expect(next.tenantId).toBe("tenant-B");
    expect(next.drafts.propertyId).toBeUndefined();
    expect(next.reviews.status).toBeUndefined();
    expect(next.detailReviewId).toBeNull();
  });

  it("adoptTenant is a no-op when the tenant is the same", () => {
    const store = useReviewsUiStore.getState();
    store.adoptTenant("tenant-A");
    store.setDraftsPropertyId("p1");
    const refBefore = useReviewsUiStore.getState();
    store.adoptTenant("tenant-A");
    const refAfter = useReviewsUiStore.getState();
    expect(refAfter.drafts.propertyId).toBe("p1");
    expect(refAfter).toBe(refBefore);
  });

  it("reset returns the store to its initial state", () => {
    const store = useReviewsUiStore.getState();
    store.setActiveTab("reviews");
    store.setDraftsPropertyId("p1");
    store.setReviewsStatus("APPROVED");
    store.setDetailReviewId("r9");
    store.reset();
    const next = useReviewsUiStore.getState();
    expect(next.activeTab).toBe("drafts");
    expect(next.drafts.propertyId).toBeUndefined();
    expect(next.reviews.status).toBeUndefined();
    expect(next.detailReviewId).toBeNull();
  });
});