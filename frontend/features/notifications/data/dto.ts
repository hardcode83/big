/**
 * UI DTOs for the notifications feature (design D10, the `features/incidents/` mould).
 *
 * The wire types come from `components["schemas"][...]`, generated from
 * `backend/openapi.json`. This module mirrors them as camelCase UI DTOs with the fields
 * enumerated by hand, so the snake_case/camelCase boundary stays at the HTTP source.
 *
 * `NotificationType` is re-exported from the generated contract on purpose and never
 * re-declared here (design D7): it is the union of the seventeen names the backend knows, and
 * typing the copy catalogue by it is what makes a missing translation fail
 * `npm run typecheck` instead of shipping a raw identifier to a cleaner's screen. Declaring
 * the list by hand would drift the day `notification-writers-gap` touches the enum.
 */
import type { components } from "@/lib/api/generated/openapi";

export type NotificationType = components["schemas"]["NotificationType"];

/**
 * One row of the inbox.
 *
 * `type` is deliberately `string`, not `NotificationType`: the backend column is a free
 * `String(100)` that admits values written before the enum existed, and the contract says so
 * (`anyOf: [NotificationType, string]`). R4.3 orders the UI to tolerate an unknown value with
 * a generic translated text, so narrowing it here would move that case from "handled" to
 * "impossible to represent" — and then to a runtime surprise.
 *
 * `subject` and `body` are NOT carried into this DTO at all (R4.2). They exist on the wire
 * and the row must never paint them: they are written in English, for an operator, and carry
 * raw UUIDs. Leaving them out of the DTO is what makes that a property of the type rather
 * than a habit of whoever writes the component.
 */
export interface NotificationDto {
  id: string;
  type: string;
  relatedType: string | null;
  relatedId: string | null;
  createdAt: string;
  readAt: string | null;
}

/** The paginated envelope of PRD §23, renamed to camelCase. */
export interface NotificationList {
  items: NotificationDto[];
  total: number;
  page: number;
  perPage: number;
  totalPages: number;
}

/**
 * Filters for the listing. `unread` omitted means "all of them", which is the backend's
 * default too (design D5).
 */
export interface NotificationFilters {
  page?: number;
  perPage?: number;
  unread?: boolean;
}
