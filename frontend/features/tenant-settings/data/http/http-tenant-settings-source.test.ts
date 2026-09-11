import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpTenantSettingsSource } from "./http-tenant-settings-source";

function buildClient(impl: ReturnType<typeof vi.fn>): ApiClient {
  return { request: impl } as unknown as ApiClient;
}

const USER_WIRE = {
  id: "u1",
  name: "Persona Existente",
  email: "existing@example.com",
  phone: "+34600000000",
  preferred_language: "es",
  role: "PROPERTY_MANAGER",
  status: "ACTIVE",
  last_login_at: "2026-09-01T08:00:00Z",
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

const USER_DTO = {
  id: "u1",
  name: "Persona Existente",
  email: "existing@example.com",
  phone: "+34600000000",
  preferredLanguage: "es",
  role: "PROPERTY_MANAGER",
  status: "ACTIVE",
  lastLoginAt: "2026-09-01T08:00:00Z",
  createdAt: "2026-08-01T10:00:00Z",
  updatedAt: "2026-09-01T10:00:00Z",
};

const TENANT_CONFIG_WIRE = {
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
};

const TENANT_CONFIG_DTO = {
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
};

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
  config: TENANT_CONFIG_WIRE,
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
  config: TENANT_CONFIG_DTO,
};

describe("HttpTenantSettingsSource", () => {
  describe("listUsers (R1.1, R1.2)", () => {
    it("maps the wire UserPageResponse (snake_case) to UserListDto (camelCase)", async () => {
      const request = vi.fn().mockResolvedValue({
        data: [USER_WIRE],
        total: 1,
        page: 1,
        per_page: 20,
        total_pages: 1,
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.listUsers("t1");

      expect(result).toEqual({
        data: [USER_DTO],
        total: 1,
        page: 1,
        perPage: 20,
        totalPages: 1,
      });
    });

    it("defaults to page 1 / 20 per page with no role/status filter sent", async () => {
      const request = vi.fn().mockResolvedValue({
        data: [],
        total: 0,
        page: 1,
        per_page: 20,
        total_pages: 0,
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.listUsers("t1");

      expect(request).toHaveBeenCalledWith("/api/v1/users", {
        query: { page: 1, per_page: 20 },
      });
    });

    it("sends role and status filters on the query string when provided (design D8)", async () => {
      const request = vi.fn().mockResolvedValue({
        data: [],
        total: 1,
        page: 1,
        per_page: 1,
        total_pages: 1,
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.listUsers("t1", {
        role: "CLEANER",
        status: "ACTIVE",
        perPage: 1,
      });

      expect(request).toHaveBeenCalledWith("/api/v1/users", {
        query: {
          page: 1,
          per_page: 1,
          role: "CLEANER",
          status: "ACTIVE",
        },
      });
    });
  });

  describe("createUser (R2.1)", () => {
    it("sends the CreateUserRequest fields and maps the created user + temporaryPassword back", async () => {
      const request = vi.fn().mockResolvedValue({
        temporary_password: "temp-pass-123",
        user: USER_WIRE,
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.createUser("t1", {
        email: "existing@example.com",
        name: "Persona Existente",
        phone: "+34600000000",
        role: "PROPERTY_MANAGER",
      });

      expect(request).toHaveBeenCalledWith("/api/v1/users", {
        method: "POST",
        body: {
          email: "existing@example.com",
          name: "Persona Existente",
          phone: "+34600000000",
          role: "PROPERTY_MANAGER",
        },
      });
      expect(result).toEqual({
        temporaryPassword: "temp-pass-123",
        user: USER_DTO,
      });
    });

    it("sends null phone and omits preferred_language when not provided", async () => {
      const request = vi.fn().mockResolvedValue({
        temporary_password: "temp-pass-456",
        user: { ...USER_WIRE, phone: null },
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.createUser("t1", {
        email: "new@example.com",
        name: "Nueva Persona",
        role: "CLEANER",
      });

      expect(request).toHaveBeenCalledWith("/api/v1/users", {
        method: "POST",
        body: {
          email: "new@example.com",
          name: "Nueva Persona",
          phone: null,
          role: "CLEANER",
        },
      });
    });

    it("sends preferred_language when provided", async () => {
      const request = vi.fn().mockResolvedValue({
        temporary_password: "temp-pass-789",
        user: USER_WIRE,
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.createUser("t1", {
        email: "existing@example.com",
        name: "Persona Existente",
        role: "PROPERTY_MANAGER",
        preferredLanguage: "en",
      });

      expect(request).toHaveBeenCalledWith("/api/v1/users", {
        method: "POST",
        body: {
          email: "existing@example.com",
          name: "Persona Existente",
          phone: null,
          preferred_language: "en",
          role: "PROPERTY_MANAGER",
        },
      });
    });
  });

  describe("getUser (R1.3)", () => {
    it("maps the wire UserResponse to UserDto, including non-ACTIVE users", async () => {
      const request = vi.fn().mockResolvedValue({
        ...USER_WIRE,
        status: "INACTIVE",
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.getUser("t1", "u1");

      expect(request).toHaveBeenCalledWith("/api/v1/users/{user_id}", {
        pathParams: { user_id: "u1" },
      });
      expect(result).toEqual({ ...USER_DTO, status: "INACTIVE" });
    });
  });

  describe("updateUser (R3.1, design D7 reactivation)", () => {
    it("sends only the fields present on the input", async () => {
      const request = vi.fn().mockResolvedValue(USER_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateUser("t1", "u1", { name: "Nuevo Nombre" });

      expect(request).toHaveBeenCalledWith("/api/v1/users/{user_id}", {
        method: "PATCH",
        pathParams: { user_id: "u1" },
        body: { name: "Nuevo Nombre" },
      });
    });

    it("sends {status: 'ACTIVE'} for reactivation with no other field", async () => {
      const request = vi.fn().mockResolvedValue(USER_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateUser("t1", "u1", { status: "ACTIVE" });

      expect(request).toHaveBeenCalledWith("/api/v1/users/{user_id}", {
        method: "PATCH",
        pathParams: { user_id: "u1" },
        body: { status: "ACTIVE" },
      });
    });

    it("maps the returned UserResponse to UserDto", async () => {
      const request = vi.fn().mockResolvedValue(USER_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.updateUser("t1", "u1", { role: "CLEANER" });

      expect(result).toEqual(USER_DTO);
    });

    it("sends every mutable field when all are present, including a null phone clear", async () => {
      const request = vi.fn().mockResolvedValue(USER_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateUser("t1", "u1", {
        email: "changed@example.com",
        name: "Nombre Cambiado",
        phone: null,
        preferredLanguage: "en",
        role: "TECHNICIAN",
        status: "SUSPENDED",
      });

      expect(request).toHaveBeenCalledWith("/api/v1/users/{user_id}", {
        method: "PATCH",
        pathParams: { user_id: "u1" },
        body: {
          email: "changed@example.com",
          name: "Nombre Cambiado",
          phone: null,
          preferred_language: "en",
          role: "TECHNICIAN",
          status: "SUSPENDED",
        },
      });
    });
  });

  describe("deactivateUser (R3.5, design D7)", () => {
    it("calls DELETE /api/v1/users/{user_id} and returns nothing", async () => {
      const request = vi.fn().mockResolvedValue(undefined);
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.deactivateUser("t1", "u1");

      expect(request).toHaveBeenCalledWith("/api/v1/users/{user_id}", {
        method: "DELETE",
        pathParams: { user_id: "u1" },
      });
      expect(result).toBeUndefined();
    });
  });

  describe("resetPassword (R4.1)", () => {
    it("posts to the reset-password route and maps user + temporaryPassword", async () => {
      const request = vi.fn().mockResolvedValue({
        temporary_password: "new-temp-pass",
        user: USER_WIRE,
      });
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.resetPassword("t1", "u1");

      expect(request).toHaveBeenCalledWith(
        "/api/v1/users/{user_id}/reset-password",
        { method: "POST", pathParams: { user_id: "u1" } },
      );
      expect(result).toEqual({
        temporaryPassword: "new-temp-pass",
        user: USER_DTO,
      });
    });
  });

  describe("getTenant (R5.1)", () => {
    it("maps the wire TenantResponse (snake_case) to TenantDto (camelCase)", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.getTenant("t1");

      expect(request).toHaveBeenCalledWith("/api/v1/tenants/{tenant_id}", {
        pathParams: { tenant_id: "t1" },
      });
      expect(result).toEqual(TENANT_DTO);
    });
  });

  describe("updateTenant (R5.3)", () => {
    it("sends only the top-level fields present on the input", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateTenant("t1", { name: "Nuevo Nombre" });

      expect(request).toHaveBeenCalledWith("/api/v1/tenants/{tenant_id}", {
        method: "PATCH",
        pathParams: { tenant_id: "t1" },
        body: { name: "Nuevo Nombre" },
      });
    });

    it("omits config entirely when not provided", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateTenant("t1", { defaultLanguage: "en" });

      const call = request.mock.calls[0][1] as { body: Record<string, unknown> };
      expect(call.body).not.toHaveProperty("config");
    });

    it("sends only the nested config fields present on the input", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateTenant("t1", {
        config: {
          ownerApprovalThresholdEur: "150.00",
          slaCriticalMinutes: 10,
        },
      });

      expect(request).toHaveBeenCalledWith("/api/v1/tenants/{tenant_id}", {
        method: "PATCH",
        pathParams: { tenant_id: "t1" },
        body: {
          config: {
            owner_approval_threshold_eur: "150.00",
            sla_critical_minutes: 10,
          },
        },
      });
    });

    it("sends every mutable field, top-level and nested, when all are present", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      await source.updateTenant("t1", {
        name: "MAGNO 2",
        billingEmail: "new-billing@example.com",
        country: "PT",
        timezone: "Europe/Lisbon",
        defaultLanguage: "en",
        config: {
          ownerApprovalThresholdEur: "200.00",
          aiConfidenceThreshold: "0.9",
          slaCriticalMinutes: 5,
          slaHighMinutes: 15,
          slaMediumMinutes: 240,
          slaLowMinutes: 480,
          checkinWindowHoursBefore: 2,
          checkoutReadyHoursAfter: 1,
          autoCreateCleaningTask: false,
          cleaningPhotoRequired: false,
          notificationEmailEnabled: false,
          notificationWhatsappEnabled: true,
          reviewRecurringIssuesTopN: 10,
        },
      });

      expect(request).toHaveBeenCalledWith("/api/v1/tenants/{tenant_id}", {
        method: "PATCH",
        pathParams: { tenant_id: "t1" },
        body: {
          name: "MAGNO 2",
          billing_email: "new-billing@example.com",
          country: "PT",
          timezone: "Europe/Lisbon",
          default_language: "en",
          config: {
            owner_approval_threshold_eur: "200.00",
            ai_confidence_threshold: "0.9",
            sla_critical_minutes: 5,
            sla_high_minutes: 15,
            sla_medium_minutes: 240,
            sla_low_minutes: 480,
            checkin_window_hours_before: 2,
            checkout_ready_hours_after: 1,
            auto_create_cleaning_task: false,
            cleaning_photo_required: false,
            notification_email_enabled: false,
            notification_whatsapp_enabled: true,
            review_recurring_issues_top_n: 10,
          },
        },
      });
    });

    it("maps the returned TenantResponse to TenantDto", async () => {
      const request = vi.fn().mockResolvedValue(TENANT_WIRE);
      const source = new HttpTenantSettingsSource(buildClient(request));

      const result = await source.updateTenant("t1", { name: "MAGNO" });

      expect(result).toEqual(TENANT_DTO);
    });
  });
});
