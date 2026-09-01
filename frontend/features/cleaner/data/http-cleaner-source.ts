import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { CleanerDataSource } from "./cleaner-source";
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
  PhotoRequirementState,
  PhotoRequirementsResponse,
} from "./dto";

type TaskResponse = components["schemas"]["CleaningTaskResponse"];
type TaskListItemResponse =
  components["schemas"]["CleaningTaskListItemResponse"];
type TaskPageResponse = components["schemas"]["CleaningTaskPageResponse"];
type TaskContextResponse =
  components["schemas"]["CleaningTaskContextResponse"];
type ChecklistResponse = components["schemas"]["ChecklistResponse"];
type ChecklistItemStateResponse =
  components["schemas"]["ChecklistItemStateResponse"];
type PhotoRequirementsWireResponse =
  components["schemas"]["PhotoRequirementsResponse"];
type PhotoRequirementStateResponse =
  components["schemas"]["PhotoRequirementStateResponse"];
type CleaningPhotoWireResponse =
  components["schemas"]["app__cleaning__api__schemas__CleaningPhotoResponse"];
type CleaningPhotoListResponse =
  components["schemas"]["CleaningPhotoListResponse"];
type TaskIncidentReportedResponse =
  components["schemas"]["TaskIncidentReportedResponse"];

/** `page` is what the paginator moves (R1.5). */
const TASKS_PER_PAGE = 20;

function mapPage<T, U>(
  page: {
    data: T[];
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
  },
  mapItem: (item: T) => U,
): PaginatedResponse<U> {
  return {
    data: page.data.map(mapItem),
    total: page.total,
    page: page.page,
    perPage: page.per_page,
    totalPages: page.total_pages,
  };
}

/** Wire → UI for the full task shape (D3, D8). */
function mapTask(value: TaskResponse): CleaningTask {
  return {
    id: value.id,
    propertyId: value.property_id,
    reservationId: value.reservation_id,
    assignedCleanerId: value.assigned_cleaner_id,
    status: value.status,
    scheduledStart: value.scheduled_start,
    scheduledEnd: value.scheduled_end,
    acceptedAt: value.accepted_at,
    startedAt: value.started_at,
    completedAt: value.completed_at,
    validationStatus: value.validation_status,
    createdAt: value.created_at,
  };
}

/**
 * The listing row carries the same fields as the full task — the backend's
 * pre-flight verdict (`assignment_blocked_by`) is irrelevant to a cleaner, but
 * the wire shape is one and we keep one mapper to avoid the divergence that
 * `tech-app` called out in its design D3.
 */
function mapListItem(value: TaskListItemResponse): CleaningTaskListItem {
  return mapTask(value);
}

/** Wire → UI for the task context (R2.2). */
function mapTaskContext(value: TaskContextResponse): CleaningTaskContext {
  return {
    propertyName: value.property_name,
    propertyInternalCode: value.property_internal_code,
    addressLine1: value.address_line1,
    addressLine2: value.address_line2,
    city: value.city,
    province: value.province,
    postalCode: value.postal_code,
    country: value.country,
    timezone: value.timezone,
    checkoutAt: value.checkout_at,
    nextCheckinDeadline: value.next_checkin_deadline,
  };
}

function mapChecklistItem(
  value: ChecklistItemStateResponse,
): CleaningChecklistItem {
  return {
    itemId: value.item_id,
    label: value.label,
    required: value.required,
    completed: value.completed,
    completedAt: value.completed_at,
    completedBy: value.completed_by,
  };
}

function mapChecklist(value: ChecklistResponse): CleaningChecklist {
  return {
    data: value.data.map(mapChecklistItem),
  };
}

function mapPhotoRequirement(
  value: PhotoRequirementStateResponse,
): PhotoRequirementState {
  return {
    photoType: value.photo_type,
    label: value.label,
    required: value.required,
    uploaded: value.uploaded,
  };
}

function mapPhotoRequirements(
  value: PhotoRequirementsWireResponse,
): PhotoRequirementsResponse {
  return {
    data: value.data.map(mapPhotoRequirement),
  };
}

/** Map one photo to the UI DTO (R2.5). `url` is copied verbatim. */
function mapPhoto(value: CleaningPhotoWireResponse): CleaningPhoto {
  return {
    id: value.id,
    cleaningTaskId: value.cleaning_task_id,
    photoType: value.photo_type,
    uploadedBy: value.uploaded_by,
    createdAt: value.created_at,
    url: value.url,
  };
}

function mapIncidentAck(
  value: TaskIncidentReportedResponse,
): CleaningIncidentReportAck {
  return {
    id: value.id,
    status: value.status,
    createdAt: value.created_at,
  };
}

/**
 * The HTTP source for the cleaner's task app (design D2).
 *
 * Eleven methods, six reads and five mutations, on the shared `ApiClient`. The
 * class is constructed with the authenticated client by the composition point
 * (`features/cleaner/data/index.ts`); UI and hooks depend only on the methods
 * of `CleanerDataSource`, never on this class directly.
 */
export class HttpCleanerSource implements CleanerDataSource {
  constructor(private readonly client: ApiClient) {}

  async listTasks(
    _tenantId: string,
    filters: CleaningFilters,
    page: number,
  ): Promise<PaginatedResponse<CleaningTaskListItem>> {
    const response: TaskPageResponse = await this.client.request<
      "/api/v1/cleaning-tasks",
      "GET"
    >("/api/v1/cleaning-tasks", {
      query: {
        page,
        per_page: TASKS_PER_PAGE,
        ...(filters.status !== undefined ? { status: filters.status } : {}),
      },
    });
    return mapPage(response, mapListItem);
  }

  async getTask(_tenantId: string, taskId: string): Promise<CleaningTask> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}",
      { pathParams: { task_id: taskId } },
    );
    return mapTask(response as TaskResponse);
  }

  async getTaskContext(
    _tenantId: string,
    taskId: string,
  ): Promise<CleaningTaskContext> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/context",
      { pathParams: { task_id: taskId } },
    );
    return mapTaskContext(response as TaskContextResponse);
  }

  async getTaskChecklist(
    _tenantId: string,
    taskId: string,
  ): Promise<CleaningChecklist> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/checklist",
      { pathParams: { task_id: taskId } },
    );
    return mapChecklist(response as ChecklistResponse);
  }

  async getTaskPhotoRequirements(
    _tenantId: string,
    taskId: string,
  ): Promise<PhotoRequirementsResponse> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/photo-requirements",
      { pathParams: { task_id: taskId } },
    );
    return mapPhotoRequirements(response as PhotoRequirementsWireResponse);
  }

  async getTaskPhotos(
    _tenantId: string,
    taskId: string,
  ): Promise<CleaningPhoto[]> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/photos",
      { pathParams: { task_id: taskId } },
    );
    return (response as CleaningPhotoListResponse).data.map(mapPhoto);
  }

  async acceptTask(_tenantId: string, taskId: string): Promise<CleaningTask> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/accept",
      { method: "POST", pathParams: { task_id: taskId } },
    );
    return mapTask(response as TaskResponse);
  }

  /**
   * The reject endpoint returns the **replacement** task per the contract
   * comment on `reject_cleaning_task_api_v1_cleaning_tasks__task_id__reject_post`.
   * The cleaner app does not need it — the view calls `removeQueries` for the
   * declined task and invalidates the list prefix — but the mapper still does
   * its job so the type stays honest at the boundary.
   */
  async rejectTask(_tenantId: string, taskId: string): Promise<CleaningTask> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/reject",
      { method: "POST", pathParams: { task_id: taskId } },
    );
    return mapTask(response as TaskResponse);
  }

  async startTask(_tenantId: string, taskId: string): Promise<CleaningTask> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/start",
      { method: "POST", pathParams: { task_id: taskId } },
    );
    return mapTask(response as TaskResponse);
  }

  async completeTask(
    _tenantId: string,
    taskId: string,
  ): Promise<CleaningTask> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/complete",
      { method: "POST", pathParams: { task_id: taskId } },
    );
    return mapTask(response as TaskResponse);
  }

  /**
   * Marks one checklist item as completed (R4.1). The endpoint answers `204`,
   * so the mapper is shaped from the `item_id` we sent; the UI invalidates
   * `cleanerKeys.checklist(t, id)` so the next read brings the canonical
   * `completed_at` and `completed_by`.
   */
  async completeChecklistItem(
    _tenantId: string,
    taskId: string,
    itemId: string,
  ): Promise<CleaningChecklistItem> {
    await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/checklist/{item_id}/complete",
      {
        method: "POST",
        pathParams: { task_id: taskId, item_id: itemId },
      },
    );
    return {
      itemId,
      label: "",
      required: false,
      completed: true,
      completedAt: null,
      completedBy: null,
    };
  }

  /**
   * Uploads one photo (R5.3). Goes through the `formData` path the transport
   * exposes since `tech-app` D2 — no manual `Content-Type`, no `JSON.stringify`,
   * the session header and the one-shot `401` retry come for free (design D9,
   * D14).
   */
  async uploadPhoto(
    _tenantId: string,
    taskId: string,
    photoType: string,
    file: File,
  ): Promise<CleaningPhoto> {
    const formData = new FormData();
    formData.append("photo_type", photoType);
    formData.append("file", file);
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/photos",
      {
        method: "POST",
        pathParams: { task_id: taskId },
        formData,
      },
    );
    return mapPhoto(response as CleaningPhotoWireResponse);
  }

  async reportIncident(
    _tenantId: string,
    taskId: string,
    input: CleaningIncidentReportInput,
  ): Promise<CleaningIncidentReportAck> {
    const response = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}/incidents",
      {
        method: "POST",
        pathParams: { task_id: taskId },
        body: { title: input.title, description: input.description },
      },
    );
    return mapIncidentAck(response as TaskIncidentReportedResponse);
  }
}