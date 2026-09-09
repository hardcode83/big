import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpApprovalsSource } from "./http-approvals-source";

function buildClient(impl: ReturnType<typeof vi.fn>): ApiClient {
  return { request: impl } as unknown as ApiClient;
}

const INCIDENT_ROW = {
  id: "a1",
  related_type: "INCIDENT",
  status: "PENDING",
  amount: "350.00",
  currency: "EUR",
  requested_at: "2026-08-12T08:00:00Z",
  responded_at: null,
  incident: {
    id: "i1",
    title: "Fuga de agua",
    category: "PLUMBING",
    severity: "HIGH",
  },
  property: {
    id: "p1",
    name: "Piso Sol",
    internal_code: "MAD-01",
  },
};

const OTHER_ROW = {
  id: "a2",
  related_type: "OTHER",
  status: "APPROVED",
  amount: "80.00",
  currency: "EUR",
  requested_at: "2026-08-10T08:00:00Z",
  responded_at: "2026-08-11T08:00:00Z",
  incident: null,
  property: {
    id: "p2",
    name: "Ático Norte",
    internal_code: "MAD-02",
  },
};

describe("HttpApprovalsSource", () => {
  describe("listApprovals (R1.1, R1.2, R1.3)", () => {
    it("maps the wire OwnerApprovalPageResponse (snake_case) to OwnerApprovalPage (camelCase)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [INCIDENT_ROW, OTHER_ROW],
        total: 2,
        page: 1,
        per_page: 20,
      });
      const source = new HttpApprovalsSource(buildClient(request));

      const result = await source.listApprovals("tenant-1");

      expect(result.items).toHaveLength(2);
      expect(result.items[0]).toEqual({
        id: "a1",
        relatedType: "INCIDENT",
        status: "PENDING",
        amount: "350.00",
        currency: "EUR",
        requestedAt: "2026-08-12T08:00:00Z",
        respondedAt: null,
        incident: {
          id: "i1",
          title: "Fuga de agua",
          category: "PLUMBING",
          severity: "HIGH",
        },
        property: {
          id: "p1",
          name: "Piso Sol",
          internalCode: "MAD-01",
        },
      });
      expect(result.items[1].incident).toBeNull();
      expect(result.total).toBe(2);
      expect(result.page).toBe(1);
      expect(result.perPage).toBe(20);
    });

    it("hits GET /api/v1/owner-approvals", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.listApprovals("tenant-1");

      expect(request.mock.calls[0][0]).toBe("/api/v1/owner-approvals");
    });

    it("emits exactly the v1 query keys: status, page, per_page (D5)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 2,
        per_page: 5,
      });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.listApprovals("tenant-1", {
        status: "APPROVED",
        page: 2,
        perPage: 5,
      });

      expect(request).toHaveBeenCalledWith("/api/v1/owner-approvals", {
        query: { status: "APPROVED", page: 2, per_page: 5 },
      });
    });

    it("emits only the keys present in the filter (undefined keys are omitted)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.listApprovals("tenant-1", { status: "PENDING" });

      expect(request.mock.calls[0][1].query).toEqual({ status: "PENDING" });
    });

    it("emits an empty query when filters are empty (the default queue — R1.2)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.listApprovals("tenant-1", {});

      expect(request.mock.calls[0][1].query).toEqual({});
    });

    it("never emits a repeatable status — a single value, never an array (D5)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 5,
      });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.listApprovals("tenant-1", {
        status: "REJECTED",
        perPage: 5,
      });

      const query = request.mock.calls[0][1].query as Record<string, unknown>;
      expect(Array.isArray(query.status)).toBe(false);
      expect(query.status).toBe("REJECTED");
    });
  });

  describe("respond (R3.1, R3.3, R3.6)", () => {
    it("POSTs status and response_notes verbatim", async () => {
      const request = vi.fn().mockResolvedValue({ id: "i1" });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.respond("tenant-1", {
        approvalId: "a1",
        status: "APPROVED",
        responseNotes: "Adelante",
      });

      expect(request).toHaveBeenCalledWith(
        "/api/v1/owner-approvals/{approval_id}/respond",
        {
          method: "POST",
          pathParams: { approval_id: "a1" },
          body: { status: "APPROVED", response_notes: "Adelante" },
        },
      );
    });

    it("omits response_notes entirely when absent, rather than sending an empty string", async () => {
      const request = vi.fn().mockResolvedValue({ id: "i1" });
      const source = new HttpApprovalsSource(buildClient(request));

      await source.respond("tenant-1", {
        approvalId: "a1",
        status: "REJECTED",
      });

      expect(request).toHaveBeenCalledWith(
        "/api/v1/owner-approvals/{approval_id}/respond",
        {
          method: "POST",
          pathParams: { approval_id: "a1" },
          body: { status: "REJECTED" },
        },
      );
      const body = request.mock.calls[0][1].body as Record<string, unknown>;
      expect(body).not.toHaveProperty("response_notes");
    });
  });
});
