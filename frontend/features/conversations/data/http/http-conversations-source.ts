import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type {
  ConversationDetailDto,
  ConversationFilters,
  ConversationList,
  ConversationSummaryDto,
  MessageDto,
  MessageList,
} from "../dto";

type ConversationResponse = components["schemas"]["ConversationResponse"];
type ConversationPageResponse = components["schemas"]["ConversationPageResponse"];
type MessageResponse = components["schemas"]["MessageResponse"];
type MessagePageResponse = components["schemas"]["MessagePageResponse"];

/** Map one list-row API response to `ConversationSummaryDto` (D3, D5). */
function mapConversationSummary(value: ConversationResponse): ConversationSummaryDto {
  return {
    id: value.id,
    channel: value.channel,
    status: value.status,
    escalationStatus: value.escalation_status,
    lastMessageAt: value.last_message_at,
    createdAt: value.created_at,
  };
}

/** Map the detail endpoint response to `ConversationDetailDto` (all 13 fields). */
function mapConversationDetail(value: ConversationResponse): ConversationDetailDto {
  return {
    id: value.id,
    propertyId: value.property_id,
    reservationId: value.reservation_id,
    guestId: value.guest_id,
    channel: value.channel,
    status: value.status,
    escalationStatus: value.escalation_status,
    language: value.language,
    aiEnabled: value.ai_enabled,
    lastMessageAt: value.last_message_at,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

/**
 * Map the messages endpoint response to `MessageDto`. `metadata` is **not**
 * mapped (see `dto.ts` — closed audit keys with no UI use case in this change).
 */
function mapMessage(value: MessageResponse): MessageDto {
  return {
    id: value.id,
    conversationId: value.conversation_id,
    senderType: value.sender_type,
    senderUserId: value.sender_user_id,
    content: value.content,
    language: value.language,
    aiGenerated: value.ai_generated,
    confidenceScore: value.confidence_score,
    intent: value.intent,
    createdAt: value.created_at,
  };
}

/**
 * The HTTP source for the conversations feature. It owns the v1 contract for
 * the list, detail, messages-list and reply endpoints, and maps snake_case
 * payloads into the camelCase UI DTOs (D3).
 *
 * The class is constructed with the authenticated `ApiClient` by the
 * composition point (`features/conversations/data/index.ts`). UI and hooks
 * depend ONLY on the methods of this class, not on the OpenAPI types.
 */
export class HttpConversationsSource {
  constructor(private readonly client: ApiClient) {}

  /**
   * List the tenant's conversations, paginated and filterable (proposal R2).
   * `tenantId` is explicit at the boundary so the source stays honest about
   * tenant scoping; the backend is the authority for tenant isolation.
   *
   * `filters` keys are camelCase (D4): the method translates the input
   * boundary into the snake_case keys the backend accepts on the wire
   * (`status`, `escalation_status`, `page`, `per_page`). `property_id` is
   * NOT in v1 and never appears here — design D4. Keys whose value is
   * `undefined` are dropped so the wire payload matches exactly what the
   * test asserts.
   */
  async listConversations(
    _tenantId: string,
    filters: ConversationFilters = {},
  ): Promise<ConversationList> {
    const query: Record<string, string | number> = {};
    if (filters.status !== undefined) query.status = filters.status;
    if (filters.escalationStatus !== undefined) {
      query.escalation_status = filters.escalationStatus;
    }
    if (filters.page !== undefined) query.page = filters.page;
    if (filters.perPage !== undefined) query.per_page = filters.perPage;
    const response = await this.client.request("/api/v1/conversations", { query });
    const page = response as ConversationPageResponse;
    return {
      items: page.items.map(mapConversationSummary),
      total: page.total,
      page: page.page,
      perPage: page.per_page,
    };
  }

  /**
   * Fetch one conversation (proposal R3). A 404 from the backend (other
   * tenant, or unknown id) surfaces as an `ApiError` thrown by the client;
   * the UI distinguishes the variant in the error mapper.
   */
  async getConversation(
    _tenantId: string,
    conversationId: string,
  ): Promise<ConversationDetailDto> {
    const response = await this.client.request("/api/v1/conversations/{conversation_id}", {
      pathParams: { conversation_id: conversationId },
    });
    return mapConversationDetail(response as ConversationResponse);
  }

  /**
   * List the messages of one conversation, paginated, in chronological
   * ascending order (R3.3 — `messaging-ai.md` R7).
   */
  async listMessages(
    _tenantId: string,
    conversationId: string,
    page: number = 1,
    perPage: number = 20,
  ): Promise<MessageList> {
    const response = await this.client.request<"/api/v1/conversations/{conversation_id}/messages", "GET">(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        pathParams: { conversation_id: conversationId },
        query: { page, per_page: perPage },
      },
    );
    const wire = response as MessagePageResponse;
    return {
      items: wire.items.map(mapMessage),
      total: wire.total,
      page: wire.page,
      perPage: wire.per_page,
    };
  }

  /**
   * Reply to a conversation as the operator (proposal R4). The body is
   * `{ content }` only — `sender_type` is **never** sent from the UI:
   * `CreateMessageRequest.sender_type` is `Literal["GUEST"] | null`, and
   * `messaging-ai.md` R7 derives `sender_type` from the caller's role when
   * the field is omitted. Sending any other value answers `422` (D9).
   */
  async replyToConversation(
    _tenantId: string,
    conversationId: string,
    input: { content: string },
  ): Promise<MessageDto> {
    const response = await this.client.request(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        method: "POST",
        pathParams: { conversation_id: conversationId },
        body: { content: input.content },
      },
    );
    return mapMessage(response as MessageResponse);
  }
}