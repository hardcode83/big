"use client";

import { useMemo } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { useActiveProperties } from "@/features/properties";
import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import {
  getStatementsDataSource,
  type OwnerStatementDetail,
  type OwnerStatementFilters,
  type OwnerStatementsPage,
} from "../data";
import { statementsKeys } from "./query-keys";

function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error("Statements requires an authenticated tenant context");
  }
  return user.tenant_id;
}

export function useStatementsList(
  filters: OwnerStatementFilters,
  page: number,
): UseQueryResult<OwnerStatementsPage> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: statementsKeys.list(tenantId, filters, page),
    queryFn: () => getStatementsDataSource().listStatements(tenantId, filters, page),
    retry: retryPolicy,
  });
}

export function useStatementDetail(
  statementId: string | null,
): UseQueryResult<OwnerStatementDetail> {
  const tenantId = useTenantId();
  const hasValidStatementId = typeof statementId === "string" && statementId.trim().length > 0;
  return useQuery({
    enabled: hasValidStatementId,
    queryKey: statementsKeys.detail(tenantId, statementId ?? ""),
    queryFn: () => {
      if (!statementId) {
        throw new Error("statementId is required");
      }
      return getStatementsDataSource().getStatement(tenantId, statementId);
    },
    retry: retryPolicy,
  });
}

/**
 * The complete active-property directory comes from the properties feature.
 * This hook deliberately does not create a statements-owned query or source.
 */
export function useStatementPropertyDirectory() {
  const properties = useActiveProperties();
  const index = useMemo(
    () => new Map((properties.data?.data ?? []).map((property) => [property.id, property])),
    [properties.data?.data],
  );
  return { ...properties, index };
}

export function useStatementsData(
  filters: OwnerStatementFilters,
  page: number,
  statementId: string | null,
) {
  const list = useStatementsList(filters, page);
  const detail = useStatementDetail(statementId);
  const propertyDirectory = useStatementPropertyDirectory();
  return { list, detail, propertyDirectory };
}
