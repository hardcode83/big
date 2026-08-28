import type {
  CleanerSummary,
  CleaningTask,
  CleaningTaskFilters,
  CleaningTaskListItem,
  PaginatedResponse,
  PropertySummary,
} from "./dto";

/**
 * The cleaning view's data-access boundary. Components and hooks depend ONLY on
 * this interface, never on a concrete implementation, which is what lets the
 * component tests inject a double without touching `lib/api`. The single runtime
 * implementation is `HttpCleaningSource`; there is no mock source, because the
 * backend has existed since the `cleaning` change and there is nothing to stand
 * in for (design D1).
 *
 * `tenantId` is explicit at the boundary so the tenant-scoped query keys stay
 * honest; it comes from the session context. The backend remains the authority
 * for tenant isolation.
 *
 * Every method rejects with `ApiError` (`lib/api`) on failure — including the
 * §23 `403`/`404`/`409`/`422` envelopes that `assignTask` can produce.
 */
export interface CleaningDataSource {
  /**
   * One page of the tenant's cleaning tasks, filtered server-side (R1.1, R3).
   *
   * `CleaningTaskListItem` and not `CleaningTask`: rows carry the assignment pre-flight,
   * which only the listing answers (design D7). `assignTask` below still returns the base
   * shape.
   */
  listTasks(
    tenantId: string,
    filters: CleaningTaskFilters,
    page: number,
  ): Promise<PaginatedResponse<CleaningTaskListItem>>;

  /** The tenant's `role=CLEANER` catalog, active and inactive alike (design D4). */
  listCleaners(tenantId: string): Promise<CleanerSummary[]>;

  /** The tenant's property catalog, for R2.1's readable identity. */
  listProperties(tenantId: string): Promise<PropertySummary[]>;

  /** Assigns or reassigns one task; `assigned_cleaner_id` is the only field sent (R4.6). */
  assignTask(
    tenantId: string,
    taskId: string,
    cleanerId: string,
  ): Promise<CleaningTask>;

  /**
   * Cancels one cleaning task (proposal `blocked-transitions-web` R2.2, R3.1).
   *
   * `reason` is required by the backend contract (`cleaning-stall-blocks-next-stay`
   * R3.1) and bounded to 500 characters; the dialog enforces both. The backend
   * resolves the property's next state through `PropertyStateMachine`, never
   * directly, so the response is the same `CleaningTask` shape the assignment
   * PATCH returns.
   */
  cancelTask(
    tenantId: string,
    taskId: string,
    reason: string,
  ): Promise<CleaningTask>;
}
