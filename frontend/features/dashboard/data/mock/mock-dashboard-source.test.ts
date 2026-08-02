import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { MockDashboardSource } from "./mock-dashboard-source";

const source = new MockDashboardSource();
const TENANT = "dev-tenant";

describe("MockDashboardSource (R3)", () => {
  it("returns dashboard cards in a §23 pagination envelope", async () => {
    const page = await source.getDashboardCards(TENANT);

    expect(page.data.length).toBeGreaterThan(0);
    expect(page.total).toBe(page.data.length);
    expect(page.page).toBe(1);
    expect(page.total_pages).toBe(1);
    // Every card carries the fields the §9.1 card render depends on.
    for (const card of page.data) {
      expect(card.propertyId).toBeTruthy();
      expect(card.propertyCode).toBeTruthy();
      expect(card.operationalState).toBeTruthy();
      expect(typeof card.openIncidentsCount).toBe("number");
    }
  });

  it("returns full detail for a known property", async () => {
    const detail = await source.getPropertyDetail(TENANT, "redes11");

    expect(detail.propertyCode).toBe("REDES11");
    expect(Array.isArray(detail.openIncidents)).toBe(true);
    expect(Array.isArray(detail.lastCleaningPhotos)).toBe(true);
    expect(Array.isArray(detail.pendingApprovals)).toBe(true);
  });

  it("rejects with a §23 404 ApiError for an unknown property detail", async () => {
    const error = await source
      .getPropertyDetail(TENANT, "unknown")
      .catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).code).toBe("NOT_FOUND");
  });

  it("returns a timeline in a §23 envelope for a known property", async () => {
    const page = await source.getPropertyTimeline(TENANT, "redes11");

    expect(page.data.length).toBeGreaterThan(0);
    expect(page.total).toBe(page.data.length);
  });

  it("applies timeline filters (actor, severity, eventType)", async () => {
    const byActor = await source.getPropertyTimeline(TENANT, "pajaritos8", {
      actorType: "GUEST",
    });
    expect(byActor.data).toHaveLength(1);
    expect(byActor.data[0]?.actorType).toBe("GUEST");

    const bySeverity = await source.getPropertyTimeline(TENANT, "pajaritos8", {
      severity: "WARNING",
    });
    expect(bySeverity.data.every((e) => e.severity === "WARNING")).toBe(true);

    const byEventType = await source.getPropertyTimeline(TENANT, "redes11", {
      eventType: "CLEANING_TASK_CREATED",
    });
    expect(byEventType.data).toHaveLength(1);
    expect(byEventType.data[0]?.eventType).toBe("CLEANING_TASK_CREATED");
  });

  it("returns a well-formed empty §23 envelope when no entry matches", async () => {
    // redes11 has no CRITICAL entries — exercises the empty pagination shape.
    const page = await source.getPropertyTimeline(TENANT, "redes11", {
      severity: "CRITICAL",
    });

    expect(page.data).toEqual([]);
    expect(page.total).toBe(0);
    expect(page.total_pages).toBe(0);
    expect(page.page).toBe(1);
  });

  it("rejects with a 404 for an unknown property timeline", async () => {
    const error = await source
      .getPropertyTimeline(TENANT, "unknown")
      .catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
  });
});
