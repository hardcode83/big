import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { OwnerStatementFilters } from "../data";

/**
 * Tenant-scoped query keys for owner statements. Every key starts with the
 * shared tenant boundary, so a tenant change cannot reuse another tenant's
 * statements or property directory cache.
 */
export const statementsKeys = {
  list: (
    tenantId: string,
    filters: OwnerStatementFilters = {},
    page?: number,
  ): QueryKey =>
    tenantScopedKey(
      tenantId,
      "statements-list",
      normalizeStatementFilters(filters, page),
    ),

  listPrefix: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "statements-list"),

  detail: (tenantId: string, statementId: string): QueryKey =>
    tenantScopedKey(tenantId, "statements-detail", statementId),

  properties: (tenantId: string): QueryKey =>
    tenantScopedKey(tenantId, "statements-properties"),
} as const;

/**
 * Normalize the filters into a fixed insertion order and canonical first
 * page. Undefined filters are omitted so equivalent requests share one key.
 */
export function normalizeStatementFilters(
  filters: OwnerStatementFilters,
  page?: number,
): Record<string, string | number> {
  const normalized: Record<string, string | number> = {};
  if (filters.propertyId !== undefined) {
    normalized.propertyId = filters.propertyId;
  }
  if (filters.periodStartFrom !== undefined) {
    normalized.periodStartFrom = filters.periodStartFrom;
  }
  if (filters.periodStartTo !== undefined) {
    normalized.periodStartTo = filters.periodStartTo;
  }
  if (filters.status !== undefined) {
    normalized.status = filters.status;
  }
  normalized.page = page ?? 1;
  return normalized;
}
