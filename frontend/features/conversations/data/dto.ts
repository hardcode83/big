/**
 * DTOs for the conversations inbox surface.
 *
 * The closed unions are aliased from the generated contract rather than
 * re-declared: a new backend value must break compilation here and in the
 * exhaustive label maps (design D7), which re-declaring them would prevent.
 * Dates are the backend's ISO-8601 strings, copied verbatim.
 */
import type { components } from "@/lib/api/generated/openapi";

/** ISO-8601 timestamp as the backend emits it — never reformatted at the boundary. */
export type IsoDateTime = string;

export type ConversationStatus = components["schemas"]["ConversationStatus"];
export type ConversationEscalationStatus =
  components["schemas"]["ConversationEscalationStatus"];
export type ConversationChannel = components["schemas"]["ConversationChannel"];
export type MessageSenderType = components["schemas"]["MessageSenderType"];
export type UserRole = components["schemas"]["UserRole"];

/**
 * Messaging's page envelope (design D3). `ConversationPageResponse` and
 * `MessagePageResponse` carry `items` and no `total_pages`, so `totalPages` is
 * derived once in the mapper instead of in every consumer. It is NOT the §23
 * envelope that `features/dashboard` models.
 */
export interface ConversationPage<T> {
  items: T[];
  page: number;
  perPage: number;
  total: number;
  totalPages: number;
}

/** One inbox row. `ConversationResponse` carries no guest name nor property code. */
export interface ConversationSummary {
  id: string;
  propertyId: string | null;
  guestId: string | null;
  reservationId: string | null;
  channel: ConversationChannel;
  status: ConversationStatus;
  escalationStatus: ConversationEscalationStatus;
  language: string;
  aiEnabled: boolean;
  lastMessageAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

/**
 * `GET /conversations/{id}`, `escalate` and `resolve` all answer the same
 * `ConversationResponse` as the list, so the detail is the same shape. Named
 * separately because the thread reads it as one conversation, not as a row.
 */
export type ConversationDetail = ConversationSummary;

/** One message in the thread. */
export interface ThreadMessage {
  id: string;
  conversationId: string;
  senderType: MessageSenderType;
  senderUserId: string | null;
  /** Verbatim prose (security.md rule 11, exception 4): rendered as text only. */
  content: string;
  language: string | null;
  intent: string | null;
  aiGenerated: boolean;
  /**
   * The decimal string the contract declares (design D8). Formatted to a
   * percentage when painted; never `Number()`-ed or rounded at the boundary.
   */
  confidenceScore: string | null;
  /** From `metadata.delivery_status` — a `FAILED` reply never reached the guest (D14). */
  deliveryStatus: string | null;
  /** From `metadata.escalation_reason` (D14). */
  escalationReason: string | null;
  createdAt: IsoDateTime;
}

/**
 * The three fields the inbox needs to label a property. Mapping here is what
 * keeps `access_notes`, `emergency_notes` and `wifi_name` — which
 * `PropertyResponse` does carry — out of the query cache (design D2).
 */
export interface PropertyLabel {
  id: string;
  internalCode: string;
  name: string;
}

/** Selected inbox filters. An absent key is not sent as a query parameter. */
export interface InboxFilters {
  status?: ConversationStatus;
  escalationStatus?: ConversationEscalationStatus;
  propertyId?: string;
}

/**
 * A message being posted. `senderType` is omitted when a manager replies (the
 * backend derives it from their role) and is `"GUEST"` when transcribing what
 * the guest said, which is what triggers the AI pipeline.
 */
export interface NewMessage {
  content: string;
  senderType?: "GUEST";
}
