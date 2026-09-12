import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  CreatedUserDto,
  CreateUserInput,
  TenantConfigDto,
  TenantDto,
  UpdateTenantInput,
  UpdateUserInput,
  UserDto,
  UserListDto,
  UserRole,
  UserStatus,
} from "../../dto";

type UserResponse = components["schemas"]["UserResponse"];
type UserPageResponse = components["schemas"]["UserPageResponse"];
type CreatedUserResponse = components["schemas"]["CreatedUserResponse"];
type TenantResponse = components["schemas"]["TenantResponse"];

/** Map one `UserResponse` to `UserDto` (R1.1, R1.3). */
function mapUser(value: UserResponse): UserDto {
  return {
    id: value.id,
    name: value.name,
    email: value.email,
    phone: value.phone,
    preferredLanguage: value.preferred_language,
    role: value.role,
    status: value.status,
    lastLoginAt: value.last_login_at,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

/** Map the `UserPageResponse` envelope to `UserListDto` (R1.1, R1.2). */
function mapUserList(value: UserPageResponse): UserListDto {
  return {
    data: value.data.map(mapUser),
    total: value.total,
    page: value.page,
    perPage: value.per_page,
    totalPages: value.total_pages,
  };
}

/** Map `CreatedUserResponse` to `CreatedUserDto` (R2.1, R4.1, design D1's secret-carrying shape). */
function mapCreatedUser(value: CreatedUserResponse): CreatedUserDto {
  return {
    user: mapUser(value.user),
    temporaryPassword: value.temporary_password,
  };
}

/** Map the nested `TenantResponse.config` to `TenantConfigDto` (R5.1). */
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

/** Map `TenantResponse` to `TenantDto` (R5.1). */
function mapTenant(value: TenantResponse): TenantDto {
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

/** Filters accepted by `listUsers` (R1.2, design D8's `role`/`status` re-use for the active-cleaner count). */
export interface UserFilters {
  page?: number;
  perPage?: number;
  role?: UserRole;
  status?: UserStatus;
}

/**
 * The HTTP source for the tenant-settings feature (design D1). It owns the v1
 * contract for the eight tenant-scoped `user-management` routes consumed by
 * this change and maps snake_case payloads into the camelCase UI DTOs of
 * `dto.ts`, following `HttpPlatformSource`'s pattern. Constructed with the
 * authenticated `ApiClient` by the composition point
 * (`features/tenant-settings/data/index.ts`); UI and hooks depend only on the
 * methods of this class, never on the OpenAPI types directly.
 *
 * `_tenantId` is an explicit, unused first parameter on every `/api/v1/users*`
 * method — mirroring `HttpReservationsSource` — so the source stays honest
 * about tenant scoping even though these routes take no `tenant_id` path
 * parameter (it is implicit in the bearer token, `user-management`
 * §Aislamiento). The `/api/v1/tenants/{tenant_id}` methods use `tenantId` for
 * real: it is a genuine path parameter there.
 */
export class HttpTenantSettingsSource {
  constructor(private readonly client: ApiClient) {}

  /** `GET /api/v1/users`, paginated and filterable by role/status (R1.1, R1.2, design D8). */
  async listUsers(
    _tenantId: string,
    filters: UserFilters = {},
  ): Promise<UserListDto> {
    const query = {
      page: filters.page ?? 1,
      per_page: filters.perPage ?? 20,
      ...(filters.role !== undefined ? { role: filters.role } : {}),
      ...(filters.status !== undefined ? { status: filters.status } : {}),
    };
    const response = await this.client.request("/api/v1/users", { query });
    return mapUserList(response as UserPageResponse);
  }

  /** `POST /api/v1/users` (R2.1). */
  async createUser(
    _tenantId: string,
    input: CreateUserInput,
  ): Promise<CreatedUserDto> {
    const response = await this.client.request("/api/v1/users", {
      method: "POST",
      body: {
        email: input.email,
        name: input.name,
        phone: input.phone ?? null,
        ...(input.preferredLanguage !== undefined
          ? { preferred_language: input.preferredLanguage }
          : {}),
        role: input.role,
      },
    });
    return mapCreatedUser(response as CreatedUserResponse);
  }

  /** `GET /api/v1/users/{user_id}` — includes non-`ACTIVE` users (R1.3). */
  async getUser(_tenantId: string, userId: string): Promise<UserDto> {
    const response = await this.client.request("/api/v1/users/{user_id}", {
      pathParams: { user_id: userId },
    });
    return mapUser(response as UserResponse);
  }

  /**
   * `PATCH /api/v1/users/{user_id}` (R3.1). Only the keys present on `input`
   * are sent — reactivation (design D7) is the same call with
   * `{status: "ACTIVE"}`.
   */
  async updateUser(
    _tenantId: string,
    userId: string,
    input: UpdateUserInput,
  ): Promise<UserDto> {
    const response = await this.client.request("/api/v1/users/{user_id}", {
      method: "PATCH",
      pathParams: { user_id: userId },
      body: {
        ...(input.email !== undefined ? { email: input.email } : {}),
        ...(input.name !== undefined ? { name: input.name } : {}),
        ...(input.phone !== undefined ? { phone: input.phone } : {}),
        ...(input.preferredLanguage !== undefined
          ? { preferred_language: input.preferredLanguage }
          : {}),
        ...(input.role !== undefined ? { role: input.role } : {}),
        ...(input.status !== undefined ? { status: input.status } : {}),
      },
    });
    return mapUser(response as UserResponse);
  }

  /**
   * `DELETE /api/v1/users/{user_id}` (R3.5, design D7) — logical deactivation
   * via its own documented endpoint, not `PATCH {status: "INACTIVE"}`.
   * Idempotent, `204`, no body to map.
   */
  async deactivateUser(_tenantId: string, userId: string): Promise<void> {
    await this.client.request("/api/v1/users/{user_id}", {
      method: "DELETE",
      pathParams: { user_id: userId },
    });
  }

  /** `POST /api/v1/users/{user_id}/reset-password` (R4.1). */
  async resetPassword(
    _tenantId: string,
    userId: string,
  ): Promise<CreatedUserDto> {
    const response = await this.client.request(
      "/api/v1/users/{user_id}/reset-password",
      { method: "POST", pathParams: { user_id: userId } },
    );
    return mapCreatedUser(response as CreatedUserResponse);
  }

  /** `GET /api/v1/tenants/{tenant_id}` — tenant + nested `TenantConfig` (R5.1). */
  async getTenant(tenantId: string): Promise<TenantDto> {
    const response = await this.client.request(
      "/api/v1/tenants/{tenant_id}",
      { pathParams: { tenant_id: tenantId } },
    );
    return mapTenant(response as TenantResponse);
  }

  /**
   * `PATCH /api/v1/tenants/{tenant_id}` (R5.3). Only the keys present on
   * `input` are sent, at either level — `config` is only included when the
   * caller sent at least one nested field, and inside it only the fields
   * actually present are forwarded (`TenantConfigPatch` is itself fully
   * optional).
   */
  async updateTenant(
    tenantId: string,
    input: UpdateTenantInput,
  ): Promise<TenantDto> {
    const config = input.config;
    const response = await this.client.request(
      "/api/v1/tenants/{tenant_id}",
      {
        method: "PATCH",
        pathParams: { tenant_id: tenantId },
        body: {
          ...(input.name !== undefined ? { name: input.name } : {}),
          ...(input.billingEmail !== undefined
            ? { billing_email: input.billingEmail }
            : {}),
          ...(input.country !== undefined ? { country: input.country } : {}),
          ...(input.timezone !== undefined
            ? { timezone: input.timezone }
            : {}),
          ...(input.defaultLanguage !== undefined
            ? { default_language: input.defaultLanguage }
            : {}),
          ...(config !== undefined
            ? {
                config:
                  config === null
                    ? null
                    : {
                        ...(config.ownerApprovalThresholdEur !== undefined
                          ? {
                              owner_approval_threshold_eur:
                                config.ownerApprovalThresholdEur,
                            }
                          : {}),
                        ...(config.aiConfidenceThreshold !== undefined
                          ? {
                              ai_confidence_threshold:
                                config.aiConfidenceThreshold,
                            }
                          : {}),
                        ...(config.slaCriticalMinutes !== undefined
                          ? { sla_critical_minutes: config.slaCriticalMinutes }
                          : {}),
                        ...(config.slaHighMinutes !== undefined
                          ? { sla_high_minutes: config.slaHighMinutes }
                          : {}),
                        ...(config.slaMediumMinutes !== undefined
                          ? { sla_medium_minutes: config.slaMediumMinutes }
                          : {}),
                        ...(config.slaLowMinutes !== undefined
                          ? { sla_low_minutes: config.slaLowMinutes }
                          : {}),
                        ...(config.checkinWindowHoursBefore !== undefined
                          ? {
                              checkin_window_hours_before:
                                config.checkinWindowHoursBefore,
                            }
                          : {}),
                        ...(config.checkoutReadyHoursAfter !== undefined
                          ? {
                              checkout_ready_hours_after:
                                config.checkoutReadyHoursAfter,
                            }
                          : {}),
                        ...(config.autoCreateCleaningTask !== undefined
                          ? {
                              auto_create_cleaning_task:
                                config.autoCreateCleaningTask,
                            }
                          : {}),
                        ...(config.cleaningPhotoRequired !== undefined
                          ? {
                              cleaning_photo_required:
                                config.cleaningPhotoRequired,
                            }
                          : {}),
                        ...(config.notificationEmailEnabled !== undefined
                          ? {
                              notification_email_enabled:
                                config.notificationEmailEnabled,
                            }
                          : {}),
                        ...(config.notificationWhatsappEnabled !== undefined
                          ? {
                              notification_whatsapp_enabled:
                                config.notificationWhatsappEnabled,
                            }
                          : {}),
                        ...(config.reviewRecurringIssuesTopN !== undefined
                          ? {
                              review_recurring_issues_top_n:
                                config.reviewRecurringIssuesTopN,
                            }
                          : {}),
                      },
              }
            : {}),
        },
      },
    );
    return mapTenant(response as TenantResponse);
  }
}
