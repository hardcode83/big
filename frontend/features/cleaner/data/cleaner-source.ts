import type {
  CleaningChecklist,
  CleaningChecklistItem,
  CleaningFilters,
  CleaningIncidentReportAck,
  CleaningIncidentReportInput,
  CleaningPhoto,
  CleaningTask,
  CleaningTaskContext,
  CleaningTaskListItem,
  PaginatedResponse,
  PhotoRequirementsResponse,
} from "./dto";

/**
 * The cleaner's data-access boundary (design D1, D2).
 *
 * Components and hooks depend ONLY on this interface, never on a concrete
 * implementation. The single runtime implementation is `HttpCleanerSource`;
 * tests inject a fake built on the same interface. Swapping the implementation
 * is a one-line change in `data/index.ts`, the single composition point.
 *
 * `tenantId` is explicit at the boundary so the tenant-scoped query keys stay
 * honest; it comes from the session context. The backend remains the authority
 * for tenant isolation — the cleaner sees only her own tasks regardless of any
 * client-side filter, by way of `CleaningActor.restrict_to_cleaner_id`.
 *
 * Every method rejects with `ApiError` (`lib/api`) on failure — including the
 * §23 `403`/`404`/`409`/`413`/`422`/`502` envelopes that the eleven routes
 * publish.
 */
export interface CleanerDataSource {
  // ── Reads ───────────────────────────────────────────────────────────────

  /**
   * One page of the cleaner-tenant's tasks, filtered server-side (R1.1,
   * R1.5). The backend applies `restrict_to_cleaner_id` from the token; no
   * client parameter widens that scope.
   */
  listTasks(
    tenantId: string,
    filters: CleaningFilters,
    page: number,
  ): Promise<PaginatedResponse<CleaningTaskListItem>>;

  /** One task by id (R2.1). */
  getTask(tenantId: string, taskId: string): Promise<CleaningTask>;

  /** The property context — name, address, timezone, window (R2.2). */
  getTaskContext(
    tenantId: string,
    taskId: string,
  ): Promise<CleaningTaskContext>;

  /** The task's checklist, in the order the template declares (R2.3). */
  getTaskChecklist(
    tenantId: string,
    taskId: string,
  ): Promise<CleaningChecklist>;

  /** The photo categories the template declares (R2.4). */
  getTaskPhotoRequirements(
    tenantId: string,
    taskId: string,
  ): Promise<PhotoRequirementsResponse>;

  /** The uploaded photos, oldest first, each with a signed URL (R2.5). */
  getTaskPhotos(tenantId: string, taskId: string): Promise<CleaningPhoto[]>;

  // ── Mutations ───────────────────────────────────────────────────────────

  /** Accepts an `ASSIGNED` task (R3.1). */
  acceptTask(tenantId: string, taskId: string): Promise<CleaningTask>;

  /**
   * Rejects an `ASSIGNED` task (R3.3). The response is still a `CleaningTask`,
   * even though the UI `removeQueries` afterwards — the source stays
   * transport-neutral (design D8).
   */
  rejectTask(tenantId: string, taskId: string): Promise<CleaningTask>;

  /** Starts an `ACCEPTED` task (R3.1). */
  startTask(tenantId: string, taskId: string): Promise<CleaningTask>;

  /**
   * Closes an `IN_PROGRESS` task (R7). The backend applies the three-clause
   * validation rule of PRD §11 and answers `409` on any clause.
   */
  completeTask(tenantId: string, taskId: string): Promise<CleaningTask>;

  /**
   * Marks one checklist item as done (R4.1). Idempotent at the backend —
   * the contract fixes the write as `INSERT ... ON CONFLICT DO UPDATE`.
   */
  completeChecklistItem(
    tenantId: string,
    taskId: string,
    itemId: string,
  ): Promise<CleaningChecklistItem>;

  /**
   * Uploads one photo for a category (R5.3). Uses `multipart/form-data` with
   * `photo_type` (the entry the user touched, not a free field) and `file`.
   */
  uploadPhoto(
    tenantId: string,
    taskId: string,
    photoType: string,
    file: File,
  ): Promise<CleaningPhoto>;

  /** Reports a maintenance incident from the task (R6.1). */
  reportIncident(
    tenantId: string,
    taskId: string,
    input: CleaningIncidentReportInput,
  ): Promise<CleaningIncidentReportAck>;
}