/**
 * UI DTOs for the conversations feature (design D3).
 *
 * The wire types come from `components["schemas"][...]` (generated from
 * `backend/openapi.json`). This module mirrors the relevant pieces as UI DTOs
 * in `camelCase`, with explicit field enumeration to keep the snake_case /
 * camelCase boundary at the HTTP source.
 *
 * `metadata` of `MessageResponse` is **not** mapped into `MessageDto`: the
 * column is a closed set of audit keys (`escalation_reason`, `template_key`,
 * `template_version`, `delivery_status`, `delivery_error_code`,
 * `source_message_id`, per `sdd/specs/messaging-ai.md` R3) with no UI use case
 * in this change. Adding it later requires a UI decision.
 */
import type { components } from "@/lib/api/generated/openapi";

export type ConversationStatus = components["schemas"]["ConversationStatus"];
export type ConversationEscalationStatus =
  components["schemas"]["ConversationEscalationStatus"];
export type ConversationChannel = components["schemas"]["ConversationChannel"];
export type MessageSenderType = components["schemas"]["MessageSenderType"];

/** One row of the conversations list (D5: six columns, no `propertyId`). */
export interface ConversationSummaryDto {
  id: string;
  channel: ConversationChannel;
  status: ConversationStatus;
  escalationStatus: ConversationEscalationStatus;
  lastMessageAt: string | null;
  createdAt: string;
}

/** Full detail of one conversation (all 13 fields of `ConversationResponse`). */
export interface ConversationDetailDto {
  id: string;
  propertyId: string | null;
  reservationId: string | null;
  guestId: string | null;
  channel: ConversationChannel;
  status: ConversationStatus;
  escalationStatus: ConversationEscalationStatus;
  language: string;
  aiEnabled: boolean;
  lastMessageAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Full detail of one message (all 11 fields of `MessageResponse` minus `metadata`). */
export interface MessageDto {
  id: string;
  conversationId: string;
  senderType: MessageSenderType;
  senderUserId: string | null;
  content: string;
  language: string | null;
  aiGenerated: boolean;
  confidenceScore: string | null;
  intent: string | null;
  createdAt: string;
}

/** Wire-shaped list envelope from the backend, renamed to camelCase. */
export interface ConversationList {
  items: ConversationSummaryDto[];
  total: number;
  page: number;
  perPage: number;
}

/** Wire-shaped list envelope for the messages of one conversation. */
export interface MessageList {
  items: MessageDto[];
  total: number;
  page: number;
  perPage: number;
}

/**
 * Filter shape for `useConversations` v1 (D4). No `propertyId` — see proposal
 * R2.2. Keys are emitted in stable order by the source so two equivalent
 * renders produce the same query key.
 */
export interface ConversationFilters {
  status?: ConversationStatus;
  escalationStatus?: ConversationEscalationStatus;
  page?: number;
  perPage?: number;
}

/**
 * Derived in the client — the backend's `ConversationPageResponse` does not
 * include `total_pages`. `lastPage` is `max(1, ceil(total / perPage))`; with
 * `total = 0`, `lastPage = 1`.
 */
export interface ConversationPagination {
  page: number;
  perPage: number;
  total: number;
  lastPage: number;
}