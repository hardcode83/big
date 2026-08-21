import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { CleaningDataSource } from "../cleaning-source";
import type {
  CleanerSummary,
  CleaningTask,
  CleaningTaskFilters,
  PaginatedResponse,
  PropertySummary,
} from "../dto";

type TaskPageResponse = components["schemas"]["CleaningTaskPageResponse"];
type TaskResponse = components["schemas"]["CleaningTaskResponse"];
type UserPageResponse = components["schemas"]["UserPageResponse"];
type UserResponse = components["schemas"]["UserResponse"];
type PropertyPageResponse = components["schemas"]["PropertyPageResponse"];
type PropertyResponse = components["schemas"]["PropertyResponse"];

/** One page of tasks per request; `page` is what the pagination control moves (R1.5). */
const TASKS_PER_PAGE = 20;

/**
 * ASSUMPTION (design D3): both catalogs are fetched as a single page of 100,
 * which is the backend's `MAX_PER_PAGE` for the three listings. A tenant with
 * more than 100 properties or more than 100 cleaners will see "identity
 * unavailable" (R2.4) from the hundredth onwards. That is the degradation R2.4
 * specifies rather than a silent failure, and it is harmless at MVP scale (two
 * flats, a handful of cleaners) — but it stops being correct as coverage and has
 * to be redone before the SaaS phase.
 */
const CATALOG_PER_PAGE = 100;

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
    per_page: page.per_page,
    total_pages: page.total_pages,
  };
}

function mapTask(value: TaskResponse): CleaningTask {
  return {
    id: value.id,
    propertyId: value.property_id,
    assignedCleanerId: value.assigned_cleaner_id,
    status: value.status,
    scheduledStart: value.scheduled_start,
    scheduledEnd: value.scheduled_end,
    createdAt: value.created_at,
  };
}

function mapCleaner(value: UserResponse): CleanerSummary {
  return {
    id: value.id,
    name: value.name,
    isActive: value.status === "ACTIVE",
  };
}

function mapProperty(value: PropertyResponse): PropertySummary {
  return {
    id: value.id,
    name: value.name,
    internalCode: value.internal_code,
  };
}

export class HttpCleaningSource implements CleaningDataSource {
  constructor(private readonly client: ApiClient) {}

  async listTasks(
    _tenantId: string,
    filters: CleaningTaskFilters,
    page: number,
  ): Promise<PaginatedResponse<CleaningTask>> {
    const response: TaskPageResponse = await this.client.request<
      "/api/v1/cleaning-tasks",
      "GET"
    >(
      "/api/v1/cleaning-tasks",
      {
        query: {
          page,
          per_page: TASKS_PER_PAGE,
          // Only the filters actually chosen travel; the backend ANDs them and
          // nothing is ever filtered client-side (R3.1–R3.3).
          ...(filters.propertyId !== undefined
            ? { property_id: filters.propertyId }
            : {}),
          ...(filters.status !== undefined ? { status: filters.status } : {}),
        },
      },
    );
    return mapPage(response, mapTask);
  }

  async listCleaners(_tenantId: string): Promise<CleanerSummary[]> {
    // No `status` filter, deliberately (design D4): a task assigned to a since
    // deactivated cleaner must still resolve her name (R2.2), and narrowing the
    // candidates to the active ones happens in the assignment control (R4.2).
    const response: UserPageResponse = await this.client.request<
      "/api/v1/users",
      "GET"
    >("/api/v1/users", {
      query: { page: 1, per_page: CATALOG_PER_PAGE, role: "CLEANER" },
    });
    return response.data.map(mapCleaner);
  }

  async listProperties(_tenantId: string): Promise<PropertySummary[]> {
    const response: PropertyPageResponse = await this.client.request<
      "/api/v1/properties",
      "GET"
    >("/api/v1/properties", {
      query: { page: 1, per_page: CATALOG_PER_PAGE },
    });
    return response.data.map(mapProperty);
  }

  async assignTask(
    _tenantId: string,
    taskId: string,
    cleanerId: string,
  ): Promise<CleaningTask> {
    const response: TaskResponse = await this.client.request(
      "/api/v1/cleaning-tasks/{task_id}",
      {
        method: "PATCH",
        pathParams: { task_id: taskId },
        body: { assigned_cleaner_id: cleanerId },
      },
    );
    return mapTask(response);
  }
}
