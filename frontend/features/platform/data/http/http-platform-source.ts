import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  CreatePlatformUserInput,
  CreateTenantInput,
  CreatedPlatformUserDto,
  PlatformUserDto,
  TenantConfigDto,
  TenantListDto,
  TenantSummaryDto,
} from "../../dto";

type TenantResponse = components["schemas"]["TenantResponse"];
type TenantPageResponse = components["schemas"]["TenantPageResponse"];
type PlatformUserResponse = components["schemas"]["PlatformUserResponse"];
type CreatedPlatformUserResponse = components["schemas"]["CreatedPlatformUserResponse"];

function mapTenantConfig(value: TenantResponse["config"]): TenantConfigDto {
  return {
    ownerApprovalThresholdEur: value.owner_approval_threshold_eur,
    aiConfidenceThreshold: value.ai_confidence_threshold,
    slaCriticalMinutes: value.sla_critical_minutes,
    slaHighMinutes: value.sla_high_minutes,
    slaMediumMinutes: value.sla_medium_minutes,
    slaLowMinutes: value.sla_low_minutes,
    checkinWindowHoursBefore: value.checkin_window_hours_before,
    checkoutReadyHoursAfter: value.checkout_ready_hours_after,
    autoCreateCleaningTask: value.auto_create_cleaning_task,
    cleaningPhotoRequired: value.cleaning_photo_required,
    storageType: value.storage_type,
    notificationEmailEnabled: value.notification_email_enabled,
    notificationWhatsappEnabled: value.notification_whatsapp_enabled,
    reviewRecurringIssuesTopN: value.review_recurring_issues_top_n,
  };
}

/** Map one `TenantResponse` to `TenantSummaryDto` (R2.4, R2.6, R3.2). */
function mapTenant(value: TenantResponse): TenantSummaryDto {
  return {
    id: value.id,
    name: value.name,
    billingEmail: value.billing_email,
    country: value.country,
    timezone: value.timezone,
    defaultLanguage: value.default_language,
    status: value.status,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    config: mapTenantConfig(value.config),
  };
}

function mapPlatformUser(value: PlatformUserResponse): PlatformUserDto {
  return {
    id: value.id,
    tenantId: value.tenant_id,
    name: value.name,
    email: value.email,
    role: value.role,
    status: value.status,
    phone: value.phone,
    preferredLanguage: value.preferred_language,
    lastLoginAt: value.last_login_at,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

/**
 * The HTTP source for the platform feature (design D3). It owns the v1 contract for the
 * three platform endpoints and maps snake_case payloads into the camelCase UI DTOs, following
 * `HttpConversationsSource`'s pattern. Constructed with the authenticated `ApiClient` by the
 * composition point (`features/platform/data/index.ts`); UI and hooks depend only on the
 * methods of this class, never on the OpenAPI types directly.
 */
export class HttpPlatformSource {
  constructor(private readonly client: ApiClient) {}

  /** `GET /api/v1/platform/tenants`, paginated, ordered `created_at` desc by the backend (R2.1). */
  async listTenants(page: number = 1, perPage: number = 20): Promise<TenantListDto> {
    const response = await this.client.request("/api/v1/platform/tenants", {
      query: { page, per_page: perPage },
    });
    const wire = response as TenantPageResponse;
    return {
      items: wire.items.map(mapTenant),
      total: wire.total,
      page: wire.page,
      perPage: wire.per_page,
      totalPages: wire.total_pages,
    };
  }

  /** `POST /api/v1/platform/tenants` (R3.1). */
  async createTenant(input: CreateTenantInput): Promise<TenantSummaryDto> {
    const response = await this.client.request("/api/v1/platform/tenants", {
      method: "POST",
      body: {
        name: input.name,
        billing_email: input.billingEmail,
        country: input.country,
        timezone: input.timezone,
        default_language: input.defaultLanguage,
      },
    });
    return mapTenant(response as TenantResponse);
  }

  /** `POST /api/v1/platform/tenants/{tenant_id}/users` (R4.1). */
  async createUserInTenant(
    tenantId: string,
    input: CreatePlatformUserInput,
  ): Promise<CreatedPlatformUserDto> {
    const response = await this.client.request(
      "/api/v1/platform/tenants/{tenant_id}/users",
      {
        method: "POST",
        pathParams: { tenant_id: tenantId },
        body: {
          full_name: input.fullName,
          email: input.email,
          phone: input.phone,
          role: input.role,
        },
      },
    );
    const created = response as CreatedPlatformUserResponse;
    return {
      user: mapPlatformUser(created.user),
      temporaryPassword: created.temporary_password,
    };
  }
}
