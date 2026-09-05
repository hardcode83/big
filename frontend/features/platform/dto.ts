/**
 * UI DTOs for the platform feature (design D3, D5).
 *
 * The wire types come from `components["schemas"][...]` (generated from
 * `backend/openapi.json`). This module mirrors the relevant pieces as UI DTOs
 * in `camelCase`, with explicit field enumeration to keep the snake_case /
 * camelCase boundary at the HTTP source (`data/http/http-platform-source.ts`).
 */
import type { components } from "@/lib/api/generated/openapi";

export type TenantStatus = components["schemas"]["TenantStatus"];
export type UserRole = components["schemas"]["UserRole"];
export type UserStatus = components["schemas"]["UserStatus"];

/** The nested configuration `TenantResponse.config` carries (R2.6). */
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
  storageType: string;
  notificationEmailEnabled: boolean;
  notificationWhatsappEnabled: boolean;
  reviewRecurringIssuesTopN: number;
}

/** One tenant, the same shape R2.6/R3.2 need for the list row and the just-created tenant. */
export interface TenantSummaryDto {
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

/** Wire-shaped list envelope from `GET /api/v1/platform/tenants`, renamed to camelCase (R2.1). */
export interface TenantListDto {
  items: TenantSummaryDto[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

/** What `useCreateTenant` accepts (R3.1) — the five fields `CreateTenantRequest` takes. */
export interface CreateTenantInput {
  name: string;
  billingEmail: string;
  country: string;
  timezone: string;
  defaultLanguage: "es" | "en";
}

/** What `useCreatePlatformUser` accepts (R4.1), scoped to a `tenantId` at the call site. */
export interface CreatePlatformUserInput {
  fullName: string;
  email: string;
  phone: string | null;
  role: UserRole;
}

/** The user shape `CreatedPlatformUserDto.user` carries (R4.1). */
export interface PlatformUserDto {
  id: string;
  tenantId: string | null;
  name: string;
  email: string;
  role: UserRole;
  status: UserStatus;
  phone: string | null;
  preferredLanguage: string;
  lastLoginAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** The user plus the one-time secret (R4.3, design D7) — never persisted beyond this shape. */
export interface CreatedPlatformUserDto {
  user: PlatformUserDto;
  temporaryPassword: string;
}
