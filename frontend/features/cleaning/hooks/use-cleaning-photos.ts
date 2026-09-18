"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { retryPolicy } from "@/lib/api/retry-policy";
import { useAuth } from "@/lib/auth";

import { getCleaningDataSource, type CleaningPhotoDto } from "../data";
import { cleaningKeys } from "./query-keys";

/**
 * Resolves the tenant id from the session, same pattern as `use-cleaning-task.ts`'s
 * `useTenantId` — a missing tenant context is a programming error, not a
 * silently-disabled query.
 */
function useTenantId(): string {
  const { user } = useAuth();
  if (!user || user.tenant_id === null) {
    throw new Error(
      "The cleaning task detail view requires an authenticated tenant context",
    );
  }
  return user.tenant_id;
}

/**
 * Every photo uploaded for one cleaning task (R2.1), same `useQuery` +
 * `retry: retryPolicy` shape as `useIncidentPhotos`
 * (`features/incidents/hooks/use-incidents.ts`). Grouping by `photoType` is
 * the gallery's job (section 3), not this hook's.
 */
export function useCleaningTaskPhotos(
  taskId: string,
): UseQueryResult<CleaningPhotoDto[]> {
  const tenantId = useTenantId();
  return useQuery({
    queryKey: cleaningKeys.photos(tenantId, taskId),
    queryFn: () => getCleaningDataSource().listPhotos(tenantId, taskId),
    retry: retryPolicy,
  });
}
