import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpPlatformSource } from "./http-platform-source";

function buildClient(impl: ReturnType<typeof vi.fn>): ApiClient {
  return { request: impl } as unknown as ApiClient;
}

const TENANT_WIRE = {
  id: "t1",
  name: "MAGNO",
  billing_email: "billing@example.com",
  country: "ES",
  timezone: "Europe/Madrid",
  default_language: "es",
  status: "ACTIVE",
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
  config: {
    owner_approval_threshold_eur: "100.00",
    ai_confidence_threshold: "0.75",
    sla_critical_minutes: 5,
    sla_high_minutes: 15,
    sla_medium_minutes: 240,
    sla_low_minutes: 480,
    checkin_window_hours_before: 2,
    checkout_ready_hours_after: 1,
    auto_create_cleaning_task: true,
    cleaning_photo_required: true,
    storage_type: "LOCAL",
    notification_email_enabled: true,
    notification_whatsapp_enabled: false,
    review_recurring_issues_top_n: 5,
  },
};

const TENANT_DTO = {
  id: "t1",
  name: "MAGNO",
  billingEmail: "billing@example.com",
  country: "ES",
  timezone: "Europe/Madrid",
  defaultLanguage: "es",
  status: "ACTIVE",
  createdAt: "2026-09-01T10:00:00Z",
  updatedAt: "2026-09-01T10:00:00Z",
  config: {
    ownerApprovalThresholdEur: "100.00",
    aiConfidenceThreshold: "0.75",
    slaCriticalMinutes: 5,
    slaHighMinutes: 15,
    slaMediumMinutes: 240,
    slaLowMinutes: 480,
    checkinWindowHoursBefore: 2,
    checkoutReadyHoursAfter: 1,
    autoCreateCleaningTask: true,
    cleaningPhotoRequired: true,
    storageType: "LOCAL",
    notificationEmailEnabled: true,
    notificationWhatsappEnabled: false,
    reviewRecurringIssuesTopN: 5,
  },
};

describe("HttpPlatformSource", () => {
  describe("listTenants (R2.1, R2.4, R2.6)", () => {
    it("maps the wire TenantPageResponse (snake_case) to TenantListDto (camelCase)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [TENANT_WIRE],
        total: 1,
        page: 1,
        per_page: 20,
        total_pages: 1,
      });
      const source = new HttpPlatformSource(buildClient(request));

      const result = await source.listTenants();

      expect(result).toEqual({
        items: [TENANT_DTO],
        total: 1,
        page: 1,
        perPage: 20,
        totalPages: 1,
      });
    });

    it("sends page/per_page on the query string, defaulting to page 1 / 20 per page", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
        total_pages: 0,
      });
      const source = new HttpPlatformSource(buildClient(request));

      await source.listTenants();
      expect(request).toHaveBeenCalledWith("/api/v1/platform/tenants", {
        query: { page: 1, per_page: 20 },
      });

      await source.listTenants(2, 10);
      expect(request).toHaveBeenCalledWith("/api/v1/platform/tenants", {
        query: { page: 2, per_page: 10 },
      });
    });
  });

  describe("createTenant (R3.1)", () => {
    it("sends the five CreateTenantRequest fields and maps the created tenant back", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpPlatformSource(buildClient(request));

      const result = await source.createTenant({
        name: "MAGNO",
        billingEmail: "billing@example.com",
        country: "ES",
        timezone: "Europe/Madrid",
        defaultLanguage: "es",
      });

      expect(request).toHaveBeenCalledWith("/api/v1/platform/tenants", {
        method: "POST",
        body: {
          name: "MAGNO",
          billing_email: "billing@example.com",
          country: "ES",
          timezone: "Europe/Madrid",
          default_language: "es",
        },
      });
      expect(result).toEqual(TENANT_DTO);
    });
  });

  describe("createUserInTenant (R4.1)", () => {
    it("posts to the named tenant's users route and maps user + temporaryPassword", async () => {
      const request = vi.fn().mockResolvedValue({
        temporary_password: "temp-pass-123",
        user: {
          id: "u1",
          tenant_id: "t1",
          name: "Persona Nueva",
          email: "new@example.com",
          role: "PROPERTY_MANAGER",
          status: "ACTIVE",
          phone: null,
          preferred_language: "es",
          last_login_at: null,
          created_at: "2026-09-01T10:00:00Z",
          updated_at: "2026-09-01T10:00:00Z",
        },
      });
      const source = new HttpPlatformSource(buildClient(request));

      const result = await source.createUserInTenant("t1", {
        fullName: "Persona Nueva",
        email: "new@example.com",
        phone: null,
        role: "PROPERTY_MANAGER",
      });

      expect(request).toHaveBeenCalledWith(
        "/api/v1/platform/tenants/{tenant_id}/users",
        {
          method: "POST",
          pathParams: { tenant_id: "t1" },
          body: {
            full_name: "Persona Nueva",
            email: "new@example.com",
            phone: null,
            role: "PROPERTY_MANAGER",
          },
        },
      );
      expect(result).toEqual({
        temporaryPassword: "temp-pass-123",
        user: {
          id: "u1",
          tenantId: "t1",
          name: "Persona Nueva",
          email: "new@example.com",
          role: "PROPERTY_MANAGER",
          status: "ACTIVE",
          phone: null,
          preferredLanguage: "es",
          lastLoginAt: null,
          createdAt: "2026-09-01T10:00:00Z",
          updatedAt: "2026-09-01T10:00:00Z",
        },
      });
    });
  });
});
