import { readFileSync } from "node:fs";
import { join } from "node:path";

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
    it("maps IncidentResponse with all 20 fields", async () => {
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
        eta_at: "2026-08-12T10:00:00Z",
        estimated_cost: null,
        approved_cost: null,
        final_cost: null,
        materials: "Junta de 12 mm",
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
        etaAt: "2026-08-12T10:00:00Z",
        estimatedCost: null,
        approvedCost: null,
        finalCost: null,
        materials: "Junta de 12 mm",
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
  describe("getIncidentContext (R2.3, R2.5)", () => {
    it("hits the context route and maps every field to camelCase", async () => {
      const request = vi.fn().mockResolvedValue({
        property_name: "Piso Sol",
        property_internal_code: "MAD-01",
        address_line1: "Calle Mayor 1",
        address_line2: null,
        city: "Madrid",
        province: "Madrid",
        postal_code: "28013",
        country: "ES",
        timezone: "Europe/Madrid",
        access_notes: "Portal 2, código 4571",
        assignment_note: "Llama al llegar",
      });
      const source = new HttpIncidentsSource(buildClient(request));

      const result = await source.getIncidentContext("tenant-1", "i1");

      expect(request).toHaveBeenCalledWith(
        "/api/v1/incidents/{incident_id}/context",
        { pathParams: { incident_id: "i1" } },
      );
      expect(result).toEqual({
        propertyName: "Piso Sol",
        propertyInternalCode: "MAD-01",
        addressLine1: "Calle Mayor 1",
        addressLine2: null,
        city: "Madrid",
        province: "Madrid",
        postalCode: "28013",
        country: "ES",
        timezone: "Europe/Madrid",
        accessNotes: "Portal 2, código 4571",
        assignmentNote: "Llama al llegar",
      });
    });

    it("emits no query parameter at all — nothing identifies the technician (R1.1)", async () => {
      const request = vi.fn().mockResolvedValue({
        property_name: "Piso Sol",
        property_internal_code: "MAD-01",
        address_line1: null,
        address_line2: null,
        city: null,
        province: null,
        postal_code: null,
        country: "ES",
        timezone: "Europe/Madrid",
        access_notes: null,
        assignment_note: null,
      });
      const source = new HttpIncidentsSource(buildClient(request));

      await source.getIncidentContext("tenant-1", "i1");

      expect(request.mock.calls[0][1]).not.toHaveProperty("query");
    });
  });

  describe("listPhotos (R5.1, R5.2)", () => {
    it("hits the photos route, maps each photo and copies `url` verbatim", async () => {
      const signed = "/api/v1/incident-photos/ph1?exp=123&sig=abc";
      const request = vi.fn().mockResolvedValue({
        items: [
          {
            id: "ph1",
            incident_id: "i1",
            stage: "BEFORE",
            uploaded_by: "u1",
            created_at: "2026-08-12T09:00:00Z",
            url: signed,
          },
        ],
      });
      const source = new HttpIncidentsSource(buildClient(request));

      const result = await source.listPhotos("tenant-1", "i1");

      expect(request).toHaveBeenCalledWith(
        "/api/v1/incidents/{incident_id}/photos",
        { pathParams: { incident_id: "i1" } },
      );
      expect(result).toEqual([
        {
          id: "ph1",
          incidentId: "i1",
          stage: "BEFORE",
          uploadedBy: "u1",
          createdAt: "2026-08-12T09:00:00Z",
          url: signed,
        },
      ]);
      expect(result[0]).not.toHaveProperty("storageKey");
      expect(result[0]).not.toHaveProperty("storage_key");
    });

    it("preserves the order the backend serves without re-sorting", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [
          { id: "a", incident_id: "i1", stage: "AFTER", uploaded_by: "u1", created_at: "2026-08-12T09:00:00Z", url: "/a" },
          { id: "b", incident_id: "i1", stage: "BEFORE", uploaded_by: "u1", created_at: "2026-08-12T08:00:00Z", url: "/b" },
        ],
      });
      const source = new HttpIncidentsSource(buildClient(request));

      const result = await source.listPhotos("tenant-1", "i1");

      expect(result.map((photo) => photo.id)).toEqual(["a", "b"]);
    });
  });

  describe("the surface these screens can reach (R2.5, R5.7)", () => {
    // R2.5 and R5.7 are prohibitions, satisfied by absence. What makes them
    // verifiable is that `HttpIncidentsSource` is the ONLY data source the
    // technician's screens reach — so pinning the exact set of routes it
    // declares is what closes them, rather than a denylist of names a new
    // method could sidestep.
    const sourceText = readFileSync(
      join(process.cwd(), "features/incidents/data/http/http-incidents-source.ts"),
      "utf8",
    );
    const declaredRoutes = [
      ...sourceText.matchAll(/this\.client\.request\(\s*\n?\s*"([^"]+)"/g),
    ].map((match) => match[1]);

    it("declares exactly the routes these screens are allowed to reach", () => {
      expect(new Set(declaredRoutes)).toEqual(
        new Set([
          "/api/v1/incidents",
          "/api/v1/incidents/{incident_id}",
          "/api/v1/incidents/{incident_id}/context",
          "/api/v1/incidents/{incident_id}/photos",
          "/api/v1/incidents/{incident_id}/accept",
          "/api/v1/incidents/{incident_id}/en-route",
          "/api/v1/incidents/{incident_id}/reject",
          "/api/v1/incidents/{incident_id}/wait-parts",
          "/api/v1/incidents/{incident_id}/resume",
          "/api/v1/incidents/{incident_id}/resolve",
        ]),
      );
    });

    it("declares no /api/v1/properties/ route — the role has no READ_PROPERTIES (R2.5)", () => {
      expect(
        declaredRoutes.filter((route) => route.startsWith("/api/v1/properties")),
      ).toEqual([]);
    });

    it("declares no photo deletion — the API exposes none (R5.7)", () => {
      expect(sourceText).not.toMatch(/method:\s*"DELETE"/);
    });
  });
  describe("the cycle mutations (R3.1, R3.3, R4.1, R5.3)", () => {
    const INCIDENT = {
      id: "i1",
      property_id: "p1",
      reservation_id: null,
      source: "GUEST",
      category: "WIFI",
      severity: "LOW",
      status: "ACCEPTED",
      title: "x",
      description: "",
      ai_summary: null,
      assigned_technician_id: "t1",
      owner_approval_required: false,
      eta_at: null,
      estimated_cost: null,
      approved_cost: null,
      final_cost: null,
      materials: null,
      resolved_at: null,
      created_at: "2026-08-12T08:00:00Z",
      updated_at: "2026-08-12T08:00:00Z",
    };

    it.each([
      ["reject", "/api/v1/incidents/{incident_id}/reject"],
      ["waitParts", "/api/v1/incidents/{incident_id}/wait-parts"],
      ["resume", "/api/v1/incidents/{incident_id}/resume"],
    ] as const)("%s POSTs its route with no body", async (method, route) => {
      const request = vi.fn().mockResolvedValue(INCIDENT);
      const source = new HttpIncidentsSource(buildClient(request));

      await source[method]("tenant-1", "i1");

      expect(request).toHaveBeenCalledWith(route, {
        method: "POST",
        pathParams: { incident_id: "i1" },
      });
    });

    it.each([
      ["accept", "/api/v1/incidents/{incident_id}/accept"],
      ["enRoute", "/api/v1/incidents/{incident_id}/en-route"],
    ] as const)("%s without an ETA omits the body entirely (R3.3)", async (method, route) => {
      const request = vi.fn().mockResolvedValue(INCIDENT);
      const source = new HttpIncidentsSource(buildClient(request));

      await source[method]("tenant-1", "i1");

      expect(request).toHaveBeenCalledWith(route, {
        method: "POST",
        pathParams: { incident_id: "i1" },
      });
      expect(request.mock.calls[0][1]).not.toHaveProperty("body");
    });

    it.each([
      ["accept", "/api/v1/incidents/{incident_id}/accept"],
      ["enRoute", "/api/v1/incidents/{incident_id}/en-route"],
    ] as const)("%s with an ETA sends it carrying a zone offset (R3.3)", async (method, route) => {
      const request = vi.fn().mockResolvedValue(INCIDENT);
      const source = new HttpIncidentsSource(buildClient(request));
      // What the ETA field produces: a device-zone instant converted with
      // `toISOString()`, so it travels with `Z` and satisfies the backend's
      // "must carry a timezone".
      const etaAt = new Date("2026-08-12T18:30:00Z").toISOString();

      await source[method]("tenant-1", "i1", etaAt);

      expect(request).toHaveBeenCalledWith(route, {
        method: "POST",
        pathParams: { incident_id: "i1" },
        body: { eta_at: etaAt },
      });
      expect(etaAt.endsWith("Z")).toBe(true);
    });

    it("resolve sends final_cost as a string and omits empty materials (D12)", async () => {
      const request = vi.fn().mockResolvedValue(INCIDENT);
      const source = new HttpIncidentsSource(buildClient(request));

      await source.resolve("tenant-1", "i1", { finalCost: "120.50", materials: "   " });

      expect(request).toHaveBeenCalledWith(
        "/api/v1/incidents/{incident_id}/resolve",
        {
          method: "POST",
          pathParams: { incident_id: "i1" },
          body: { final_cost: "120.50" },
        },
      );
      const body = request.mock.calls[0][1].body as Record<string, unknown>;
      expect(typeof body.final_cost).toBe("string");
      expect(body).not.toHaveProperty("materials");
    });

    it("resolve sends trimmed materials when there are any", async () => {
      const request = vi.fn().mockResolvedValue(INCIDENT);
      const source = new HttpIncidentsSource(buildClient(request));

      await source.resolve("tenant-1", "i1", {
        finalCost: "12.00",
        materials: "  Junta de 12 mm  ",
      });

      expect(request.mock.calls[0][1].body).toEqual({
        final_cost: "12.00",
        materials: "Junta de 12 mm",
      });
    });

    it("uploadPhoto travels over the formData path with `file` and `stage` (R5.3, D2)", async () => {
      const request = vi.fn().mockResolvedValue({
        id: "ph1",
        incident_id: "i1",
        stage: "AFTER",
        uploaded_by: "u1",
        created_at: "2026-08-12T09:00:00Z",
        url: "/api/v1/incident-photos/ph1?exp=1&sig=a",
      });
      const source = new HttpIncidentsSource(buildClient(request));
      const file = new File(["bytes"], "after.jpg", { type: "image/jpeg" });

      const result = await source.uploadPhoto("tenant-1", "i1", file, "AFTER");

      const options = request.mock.calls[0][1];
      expect(request.mock.calls[0][0]).toBe(
        "/api/v1/incidents/{incident_id}/photos",
      );
      expect(options.method).toBe("POST");
      expect(options).not.toHaveProperty("body");
      const formData = options.formData as FormData;
      expect(formData).toBeInstanceOf(FormData);
      expect(formData.get("stage")).toBe("AFTER");
      expect(formData.get("file")).toBe(file);
      expect(result.stage).toBe("AFTER");
    });
  });
});
