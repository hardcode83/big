import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

import type { CleaningTask } from "../data/dto";

/**
 * The UI states `CleaningTaskDetailView` renders (proposal R1.2/R1.4, design D5/D12).
 *
 * Mirrors `IncidentsErrorState` (`features/incidents/lib/error-mapping.ts`) — a
 * discriminated union the view switches on, with `success` generic over the
 * typed DTO. Two differences from the incidents mapper:
 *
 * 1. The `error` variant carries the `refetch` callback, not the raw query.
 *    The detail view's `ErrorState` (R1.4) only needs to re-trigger the read;
 *    it has no business poking the TanStack result itself.
 * 2. The `success` variant is closed over `CleaningTask` (the manager-detail
 *    shape, design D11) — not generic. The detail page has only one
 *    consumer and one DTO.
 */
export type CleaningDetailState =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "validation" }
  | { kind: "error"; refetch: () => void }
  | { kind: "success"; data: CleaningTask };

/**
 * Maps a TanStack Query result to a discriminated UI state for the cleaning
 * task detail view (R1.2/R1.4, design D5/D12). Pure mapper — no React hooks
 * internally, no i18n strings.
 *
 * The table is by HTTP **status**, with `404` accepted by number even though
 * the generated contract (`backend/openapi.json` →
 * `get_cleaning_task_api_v1_cleaning_tasks__task_id__get`) does not list it
 * in `responses`. The `apiClient` throws `ApiError` with `status: 404`
 * regardless, so the switch routes correctly; the contract gap is left for
 * `api-contract-export` to close, not here (design D12).
 *
 * - `403` → `forbidden` — `READ_CLEANING_TASKS` absent (should not happen
 *   for `PROPERTY_MANAGER` / `TENANT_OWNER`, but covered for deploy-skew).
 * - `404` → `not-found` — task does not exist or belongs to another tenant.
 * - `422` → `validation` — malformed id (UUID check on the backend).
 * - anything else (`5xx`, `TypeError`, network, unknown `4xx`) → `error`
 *   with the caller's `refetch`, so the `ErrorState` retry button can
 *   re-fire the read without a page reload.
 *
 * The `401` case is intentionally absent: a `401` here would mean the
 * session expired between the read and the UI, and that flow is owned by the
 * authenticated client (`lib/api/authenticated-client.ts`), not by this
 * view — same reasoning the incidents mapper applies (R5.4).
 */
export function mapCleaningDetailError(
  query: Pick<
    UseQueryResult<CleaningTask, Error>,
    "isPending" | "isError" | "error" | "data"
  >,
  refetch: () => void,
): CleaningDetailState {
  if (query.isPending) {
    return { kind: "loading" };
  }
  if (query.isError) {
    const error = query.error as Error;
    if (error instanceof ApiError) {
      if (error.status === 403) {
        return { kind: "forbidden" };
      }
      if (error.status === 404) {
        return { kind: "not-found" };
      }
      if (error.status === 422) {
        return { kind: "validation" };
      }
    }
    return { kind: "error", refetch };
  }
  return { kind: "success", data: query.data as CleaningTask };
}
