/**
 * UI DTOs for the tenant-settings feature (design D1, D2).
 *
 * The wire types come from `components["schemas"][...]` (generated from
 * `backend/openapi.json`). This module mirrors the relevant `user-management`
 * shapes as UI DTOs in `camelCase`, with explicit field enumeration to keep
 * the snake_case / camelCase boundary at the HTTP source
 * (`data/http/http-tenant-settings-source.ts`), the same pattern
 * `features/platform/dto.ts` and `features/reservations/data/dto.ts` follow.
 *
 * `UserDto` mirrors `UserResponse` — the tenant-scoped user shape, which
 * (unlike `PlatformUserResponse`) carries no `tenant_id`: the tenant is
 * implicit in the token, never a field on the resource (`user-management`
 * §Aislamiento).
 */
import type { components } from "@/lib/api/generated/openapi";

export type UserRole = components["schemas"]["UserRole"];
export type UserStatus = components["schemas"]["UserStatus"];
export type TenantStatus = components["schemas"]["TenantStatus"];
export type StorageType = components["schemas"]["StorageType"];

/** One user of the tenant (R1.3), mirrors `UserResponse`. */
export interface UserDto {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  preferredLanguage: string;
  role: UserRole;
  status: UserStatus;
  lastLoginAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** `GET /api/v1/users` envelope (R1.1), mirrors `UserPageResponse` — the older `{data, ...}` shape. */
export interface UserListDto {
  data: UserDto[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

/** The user plus the one-time secret (R2.1, R4.1), mirrors `CreatedUserResponse`. */
export interface CreatedUserDto {
  user: UserDto;
  temporaryPassword: string;
}

/** The nested configuration `TenantResponse.config` carries, mirrors `TenantConfigResponse` (R5.1). */
export interface TenantConfigDto {
  ownerApprovalThresholdEur: string;
  aiConfidenceThreshold: string;
  slaCriticalMinutes: number;
  slaHighMinutes: number;
  slaMediumMinutes: number;
  slaLowMinutes: number;
  checkinWindowHoursBefore: number;
  checkoutReadyHoursAfter: number;
  autoCreateCleaningTask: boolean;
  cleaningPhotoRequired: boolean;
  storageType: StorageType;
  notificationEmailEnabled: boolean;
  notificationWhatsappEnabled: boolean;
  reviewRecurringIssuesTopN: number;
}

/** The tenant with its configuration nested (R5.1), mirrors `TenantResponse`. */
export interface TenantDto {
  id: string;
  name: string;
  billingEmail: string;
  country: string;
  timezone: string;
  defaultLanguage: string;
  status: TenantStatus;
  createdAt: string;
  updatedAt: string;
  config: TenantConfigDto;
}

/** What `useCreateUser` accepts (R2.1), mirrors `CreateUserRequest`. */
export interface CreateUserInput {
  email: string;
  name: string;
  phone?: string | null;
  preferredLanguage?: string;
  role: UserRole;
}

/**
 * What `useUpdateUser` accepts (R3.1, R3.3, D7's reactivation via
 * `{status: "ACTIVE"}`), mirrors `UpdateUserRequest`. Every field optional —
 * only the ones present are sent, so the source only serialises keys that
 * are actually part of the input object (see
 * `http-tenant-settings-source.ts`'s `mapUpdateUserInput`).
 */
export interface UpdateUserInput {
  email?: string | null;
  name?: string | null;
  phone?: string | null;
  preferredLanguage?: string | null;
  role?: UserRole | null;
  status?: UserStatus | null;
}

/**
 * The nested `config` patch `UpdateTenantInput` carries, mirrors
 * `TenantConfigPatch`. `ownerApprovalThresholdEur`/`aiConfidenceThreshold`
 * stay `string | number` (never narrowed to `string`) because the generated
 * `TenantConfigPatch` schema itself types them that way: a `Numeric` field is
 * legal on the wire as a decimal string, but nothing yet in this codebase
 * forced the input side of that convention, so this is the first caller of
 * it. Callers should send the exact decimal-precision string the backend
 * expects rather than a JS `number`, the same way `TenantConfigDto` above
 * receives it back as a `string` on read.
 */
export interface UpdateTenantConfigInput {
  ownerApprovalThresholdEur?: string | number | null;
  aiConfidenceThreshold?: string | number | null;
  slaCriticalMinutes?: number | null;
  slaHighMinutes?: number | null;
  slaMediumMinutes?: number | null;
  slaLowMinutes?: number | null;
  checkinWindowHoursBefore?: number | null;
  checkoutReadyHoursAfter?: number | null;
  autoCreateCleaningTask?: boolean | null;
  cleaningPhotoRequired?: boolean | null;
  notificationEmailEnabled?: boolean | null;
  notificationWhatsappEnabled?: boolean | null;
  reviewRecurringIssuesTopN?: number | null;
}

/**
 * What `useUpdateTenant` accepts (R5.3), mirrors `UpdateTenantRequest`.
 * `status` is deliberately absent — the backend rejects it with `422`
 * (suspending your own tenant locks every user out with no way back through
 * the API) and this UI exposes no control for it (proposal "Out of scope").
 */
export interface UpdateTenantInput {
  name?: string | null;
  billingEmail?: string | null;
  country?: string | null;
  timezone?: string | null;
  defaultLanguage?: string | null;
  config?: UpdateTenantConfigInput | null;
}
