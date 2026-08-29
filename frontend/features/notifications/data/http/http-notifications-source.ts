import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { NotificationDto, NotificationFilters, NotificationList } from "../dto";

type NotificationResponse = components["schemas"]["NotificationResponse"];
type NotificationPageResponse = components["schemas"]["NotificationPageResponse"];
type UnreadCountResponse = components["schemas"]["UnreadCountResponse"];
type MarkAllReadResponse = components["schemas"]["MarkAllReadResponse"];

/**
 * Map one wire row to the UI DTO.
 *
 * `subject` and `body` are on `value` and are deliberately dropped here (R4.2). This function
 * is the only place they could have entered the client, so dropping them here is what makes
 * "the row never shows the operator's English text" a fact about the data rather than a rule
 * a component has to remember.
 */
function mapNotification(value: NotificationResponse): NotificationDto {
  return {
    id: value.id,
    type: value.notification_type,
    relatedType: value.related_type,
    relatedId: value.related_id,
    createdAt: value.created_at,
    readAt: value.read_at,
  };
}

/**
 * The HTTP source for the notifications feature (design D10).
 *
 * It owns the four operations that close the in-app cycle: list (optionally narrowed to the
 * unread), count the unread, acknowledge one, acknowledge all. It is constructed with the
 * authenticated `ApiClient` by the composition point (`features/notifications/data/index.ts`);
 * hooks and components depend only on these methods, never on the OpenAPI types.
 *
 * `tenantId` is explicit at the boundary, as in `features/incidents/`, so the source stays
 * honest about tenant scoping — but the backend is the authority, and it derives both the
 * tenant and the recipient from the token. Nothing here can widen that.
 */
export class HttpNotificationsSource {
  constructor(private readonly client: ApiClient) {}

  /**
   * One page of the caller's own notifications (R2.3).
   *
   * A filter left `undefined` is omitted from the query rather than sent empty, so the wire
   * payload is exactly what the test asserts. `unread` is only ever sent as `true`: the
   * backend treats absent and `false` alike (design D5), so sending `false` would be a
   * parameter that changes nothing.
   */
  async listNotifications(
    _tenantId: string,
    filters: NotificationFilters = {},
  ): Promise<NotificationList> {
    const query = {
      ...(filters.page !== undefined ? { page: filters.page } : {}),
      ...(filters.perPage !== undefined ? { per_page: filters.perPage } : {}),
      ...(filters.unread ? { unread: true } : {}),
    };
    const response = (await this.client.request("/api/v1/notifications", {
      query,
    })) as NotificationPageResponse;
    return {
      items: response.data.map(mapNotification),
      total: response.total,
      page: response.page,
      perPage: response.per_page,
      totalPages: response.total_pages,
    };
  }

  /** How many unread the caller has (R2.2). One request, whatever the page size. */
  async countUnread(_tenantId: string): Promise<number> {
    const response = (await this.client.request(
      "/api/v1/notifications/unread-count",
    )) as UnreadCountResponse;
    return response.unread;
  }

  /**
   * Acknowledge one notification (R5.1). Answers nothing: the route is a `204`.
   *
   * A `404` — unknown, somebody else's, another tenant's — surfaces as an `ApiError` thrown
   * by the client, and `lib/error-mapping.ts` is what turns it into a translated key.
   */
  async markRead(_tenantId: string, notificationId: string): Promise<void> {
    await this.client.request("/api/v1/notifications/{notification_id}/read", {
      method: "POST",
      pathParams: { notification_id: notificationId },
    });
  }

  /** Acknowledge every unread notification of the caller (R5.2); answers how many moved. */
  async markAllRead(_tenantId: string): Promise<number> {
    const response = (await this.client.request("/api/v1/notifications/read-all", {
      method: "POST",
    })) as MarkAllReadResponse;
    return response.updated;
  }
}
