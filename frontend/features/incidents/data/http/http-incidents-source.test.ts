import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpIncidentsSource } from "./http-incidents-source";

function buildClient(impl: ReturnType<typeof vi.fn>): ApiClient {
  return { request: impl } as unknown as ApiClient;
}

describe("HttpIncidentsSource", () => {
  describe("listIncidents (D3, D4)", () => {
    it("maps the wire IncidentPageResponse (snake_case) to IncidentList (camelCase), preserving the {items, total, page, per_page} envelope without total_pages", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [
          {
            id: "01",
            property_id: "p1",
            reservation_id: null,
            source: "GUEST",
            category: "WIFI",
            severity: "LOW",
            status: "CLASSIFIED",
            title: "WiFi va lento",
            description: "...",
            ai_summary: null,
            assigned_technician_id: null,
            owner_approval_required: false,
            estimated_cost: null,
            approved_cost: null,
            final_cost: null,
            resolved_at: null,
            created_at: "2026-08-12T08:00:00Z",
            updated_at: "2026-08-12T08:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        per_page: 20,
      });
      const source = new HttpIncidentsSource(buildClient(request));

      const result = await source.listIncidents("tenant-1");

      expect(result.items).toHaveLength(1);
      expect(result.items[0]).toEqual({
        id: "01",
        status: "CLASSIFIED",
        severity: "LOW",
        category: "WIFI",
        source: "GUEST",
        title: "WiFi va lento",
        createdAt: "2026-08-12T08:00:00Z",
      });
      expect(result.total).toBe(1);
      expect(result.page).toBe(1);
      expect(result.perPage).toBe(20);
      expect(result).not.toHaveProperty("totalPages");
      expect(result).not.toHaveProperty("total_pages");
    });

    it("emits exactly the v1 query keys: status, severity, page, per_page; filters are mapped one-to-one; no extra keys", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 2,
        per_page: 20,
      });
      const source = new HttpIncidentsSource(buildClient(request));

      await source.listIncidents("tenant-1", {
        status: "OPEN",
        severity: "HIGH",
        page: 2,
        perPage: 20,
      });

      expect(request).toHaveBeenCalledWith("/api/v1/incidents", {
        query: { status: "OPEN", severity: "HIGH", page: 2, per_page: 20 },
      });
    });

    it("does NOT add property_id under any branch (D4)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpIncidentsSource(buildClient(request));

      await source.listIncidents("tenant-1", {
        status: "OPEN",
        severity: "HIGH",
        page: 2,
        perPage: 20,
      });

      expect(request.mock.calls[0][1].query).not.toHaveProperty("property_id");
      expect(request.mock.calls[0][1].query).not.toHaveProperty("propertyId");
    });

    it("emits only the keys present in the filter (undefined keys are omitted, no extra keys)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpIncidentsSource(buildClient(request));

      await source.listIncidents("tenant-1", { severity: "HIGH" });

      expect(request.mock.calls[0][1].query).toEqual({ severity: "HIGH" });
    });

    it("emits an empty query when filters are empty (defaults belong to the backend)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpIncidentsSource(buildClient(request));

      await source.listIncidents("tenant-1", {});

      expect(request.mock.calls[0][1].query).toEqual({});
    });
  });

  describe("getIncident (D3)", () => {
    it("maps IncidentResponse with all 18 fields", async () => {
      const request = vi.fn().mockResolvedValue({
        id: "i1",
        property_id: "p1",
        reservation_id: "r1",
        source: "GUEST",
        category: "WIFI",
        severity: "LOW",
        status: "CLASSIFIED",
        title: "WiFi va lento",
        description: "El huésped reporta que el WiFi va muy lento",
        ai_summary: null,
        assigned_technician_id: null,
        owner_approval_required: false,
        estimated_cost: null,
        approved_cost: null,
        final_cost: null,
        resolved_at: null,
        created_at: "2026-08-12T08:00:00Z",
        updated_at: "2026-08-12T08:00:00Z",
      });
      const source = new HttpIncidentsSource(buildClient(request));

      const result = await source.getIncident("tenant-1", "i1");

      expect(result).toEqual({
        id: "i1",
        propertyId: "p1",
        reservationId: "r1",
        source: "GUEST",
        category: "WIFI",
        severity: "LOW",
        status: "CLASSIFIED",
        title: "WiFi va lento",
        description: "El huésped reporta que el WiFi va muy lento",
        aiSummary: null,
        assignedTechnicianId: null,
        ownerApprovalRequired: false,
        estimatedCost: null,
        approvedCost: null,
        finalCost: null,
        resolvedAt: null,
        createdAt: "2026-08-12T08:00:00Z",
        updatedAt: "2026-08-12T08:00:00Z",
      });
    });

    it("passes description through the mapper without transforming it (D7 — plain text in UI)", async () => {
      const dangerous = "<script>alert(1)</script>\nLínea 2";
      const request = vi.fn().mockResolvedValue({
        id: "i1",
        property_id: "p1",
        reservation_id: null,
        source: "GUEST",
        category: "WIFI",
        severity: "LOW",
        status: "OPEN",
        title: "x",
        description: dangerous,
        ai_summary: null,
        assigned_technician_id: null,
        owner_approval_required: false,
        estimated_cost: null,
        approved_cost: null,
        final_cost: null,
        resolved_at: null,
        created_at: "2026-08-12T08:00:00Z",
        updated_at: "2026-08-12T08:00:00Z",
      });
      const source = new HttpIncidentsSource(buildClient(request));

      const result = await source.getIncident("tenant-1", "i1");

      expect(result.description).toBe(dangerous);
    });

    it("passes the id through pathParams.incident_id", async () => {
      const request = vi.fn().mockResolvedValue({
        id: "i1",
        property_id: "p1",
        reservation_id: null,
        source: "GUEST",
        category: "WIFI",
        severity: "LOW",
        status: "OPEN",
        title: "x",
        description: "",
        ai_summary: null,
        assigned_technician_id: null,
        owner_approval_required: false,
        estimated_cost: null,
        approved_cost: null,
        final_cost: null,
        resolved_at: null,
        created_at: "2026-08-12T08:00:00Z",
        updated_at: "2026-08-12T08:00:00Z",
      });
      const source = new HttpIncidentsSource(buildClient(request));

      await source.getIncident("tenant-1", "i1");

      expect(request).toHaveBeenCalledWith(
        "/api/v1/incidents/{incident_id}",
        { pathParams: { incident_id: "i1" } },
      );
    });
  });
});