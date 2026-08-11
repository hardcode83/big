import { describe, expect, it, vi } from "vitest";

import { ApiError, type ApiClient } from "@/lib/api";

import { HttpDashboardSource } from "./http-dashboard-source";

function sourceWith(response: unknown): {
  source: HttpDashboardSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  const client = { request } as unknown as ApiClient;
  return { source: new HttpDashboardSource(client), request };
}

describe("HttpDashboardSource", () => {
  it("maps the current cards response and preserves its page envelope", async () => {
    const { source, request } = sourceWith({
      data: [
        {
          property_id: "property-1",
          property_code: "REDES11",
          operational_state: "AWAITING_CLEANING",
          current_or_next_reservation: null,
          cleaning_status: null,
          open_incidents_count: 0,
          next_action: null,
          last_event_label: "Cleaning created",
          last_event_at: "2026-08-10T09:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      per_page: 20,
      total_pages: 1,
    });

    await expect(source.getDashboardCards("tenant-1")).resolves.toEqual({
      data: [
        {
          propertyId: "property-1",
          propertyCode: "REDES11",
          operationalState: "AWAITING_CLEANING",
          currentOrNextReservation: null,
          cleaningStatus: null,
          openIncidentsCount: 0,
          nextAction: null,
          lastEventLabel: "Cleaning created",
          lastEventAt: "2026-08-10T09:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      per_page: 20,
      total_pages: 1,
    });
    expect(request).toHaveBeenCalledWith("/api/v1/dashboard/properties");
  });

  it("maps only the fields present in the current detail aggregate", async () => {
    const { source, request } = sourceWith({
      property_id: "property-1",
      property_code: "REDES11",
      operational_state: "AWAITING_CLEANING",
      current_or_next_reservation: {
        id: "reservation-1",
        reference: "Booking #1",
        guest_name: "Laura Gómez",
        check_in: "2026-08-12",
        check_out: "2026-08-15",
      },
      guest: { name: "Laura Gómez" },
      access: { label: "Pending" },
      cleaning_status: "Pending assignment",
      last_cleaning_photos: [
        {
          id: "photo-1",
          url: "https://cdn.example/photo-1",
          taken_at: "2026-08-10T09:00:00Z",
        },
      ],
      open_incidents: [
        {
          id: "incident-1",
          title: "Leak",
          severity: "MEDIUM",
          opened_at: "2026-08-10T08:00:00Z",
        },
      ],
      financial: {
        currency: "EUR",
        reservation_total: "612.50",
        pending_expenses: null,
      },
      notes: null,
      pending_approvals: [
        { id: "approval-1", label: "Repair", amount: "120.25", currency: "EUR" },
      ],
    });

    await expect(source.getPropertyDetail("tenant-1", "property-1")).resolves.toEqual({
      propertyId: "property-1",
      propertyCode: "REDES11",
      operationalState: "AWAITING_CLEANING",
      currentOrNextReservation: {
        id: "reservation-1",
        reference: "Booking #1",
        guestName: "Laura Gómez",
        checkIn: "2026-08-12",
        checkOut: "2026-08-15",
      },
      guest: { name: "Laura Gómez" },
      access: { label: "Pending" },
      cleaningStatus: "Pending assignment",
      lastCleaningPhotos: [
        { id: "photo-1", url: "https://cdn.example/photo-1", takenAt: "2026-08-10T09:00:00Z" },
      ],
      openIncidents: [
        { id: "incident-1", title: "Leak", severity: "MEDIUM", openedAt: "2026-08-10T08:00:00Z" },
      ],
      financial: {
        currency: "EUR",
        reservationTotal: 612.5,
        pendingExpenses: null,
      },
      notes: null,
      pendingApprovals: [
        { id: "approval-1", label: "Repair", amount: 120.25, currency: "EUR" },
      ],
    });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/properties/{property_id}/dashboard",
      { pathParams: { property_id: "property-1" } },
    );
  });

  it("serializes only defined timeline filters and preserves response order", async () => {
    const { source, request } = sourceWith({
      data: [
        {
          id: "event-2",
          occurred_at: "2026-08-10T10:00:00Z",
          actor_type: "USER",
          event_type: "INCIDENT_CREATED",
          severity: "WARNING",
          title: "Incident",
          description: null,
        },
        {
          id: "event-1",
          occurred_at: "2026-08-10T09:00:00Z",
          actor_type: "SYSTEM",
          event_type: "PROPERTY_STATE_CHANGED",
          severity: "INFO",
          title: "State changed",
          description: "The state changed",
        },
      ],
      total: 2,
      page: 1,
      per_page: 20,
      total_pages: 1,
    });

    await expect(
      source.getPropertyTimeline("tenant-1", "property-1", {
        eventType: "INCIDENT_CREATED",
        severity: "WARNING",
        actorType: "USER",
        from: "2026-08-01T00:00:00Z",
        to: "2026-08-31T23:59:59Z",
      }),
    ).resolves.toMatchObject({
      data: [
        expect.objectContaining({ id: "event-2" }),
        expect.objectContaining({ id: "event-1" }),
      ],
    });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/timeline/{property_id}",
      {
        pathParams: { property_id: "property-1" },
        query: {
          event_type: "INCIDENT_CREATED",
          severity: "WARNING",
          actor_type: "USER",
          from: "2026-08-01T00:00:00Z",
          to: "2026-08-31T23:59:59Z",
        },
      },
    );
  });

  it("omits undefined timeline filters and never calls out-of-scope routes", async () => {
    const { source, request } = sourceWith({
      data: [],
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    });

    await source.getPropertyTimeline("tenant-1", "property-1", {
      eventType: undefined,
      severity: undefined,
      actorType: undefined,
      from: undefined,
      to: undefined,
    });

    expect(request).toHaveBeenCalledWith(
      "/api/v1/timeline/{property_id}",
      { pathParams: { property_id: "property-1" }, query: {} },
    );
    const requestedPaths = request.mock.calls.map(([path]) => path);
    expect(requestedPaths).not.toContain("/api/v1/timeline");
    expect(requestedPaths).not.toContain("/api/v1/properties/{property_id}/state");
  });

  it.each([
    [401, "UNAUTHORIZED"],
    [404, "NOT_FOUND"],
    [422, "VALIDATION_ERROR"],
    [500, "INTERNAL_SERVER_ERROR"],
  ] as const)(
    "propagates ApiError status %s without wrapping, domain translation, or adapter retry",
    async (status, code) => {
      const error = new ApiError({
        code,
        message: `API error ${status}`,
        status,
      });
      const request = vi.fn().mockRejectedValue(error);
      const source = new HttpDashboardSource({ request } as unknown as ApiClient);

      await expect(source.getPropertyDetail("tenant-1", "missing")).rejects.toBe(error);
      expect(request).toHaveBeenCalledTimes(1);
    },
  );

  it.each([
    [404, "NOT_FOUND"],
    [422, "VALIDATION_ERROR"],
    [500, "INTERNAL_SERVER_ERROR"],
  ] as const)(
    "propagates timeline ApiError status %s without retrying",
    async (status, code) => {
      const error = new ApiError({
        code,
        message: `API error ${status}`,
        status,
      });
      const request = vi.fn().mockRejectedValue(error);
      const source = new HttpDashboardSource({ request } as unknown as ApiClient);

      await expect(
        source.getPropertyTimeline("tenant-1", "property-1"),
      ).rejects.toBe(error);
      expect(request).toHaveBeenCalledTimes(1);
      expect(request).toHaveBeenCalledWith(
        "/api/v1/timeline/{property_id}",
        { pathParams: { property_id: "property-1" }, query: {} },
      );
    },
  );
});
