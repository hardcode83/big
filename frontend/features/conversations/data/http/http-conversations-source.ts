import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";

import type { ConversationsDataSource } from "../conversations-source";
import type {
  ConversationDetail,
  ConversationPage,
  ConversationSummary,
  InboxFilters,
  NewMessage,
  PropertyLabel,
  ThreadMessage,
} from "../dto";

type ConversationResponse = components["schemas"]["ConversationResponse"];
type ConversationPageResponse = components["schemas"]["ConversationPageResponse"];
type MessageResponse = components["schemas"]["MessageResponse"];
type MessagePageResponse = components["schemas"]["MessagePageResponse"];
type PropertyPageResponse = components["schemas"]["PropertyPageResponse"];
type PropertyListItem = PropertyPageResponse["data"][number];

/** `per_page` ceiling of `GET /api/v1/properties`; R1.7 asks for a single query. */
const PROPERTY_LABELS_PER_PAGE = 100;

/**
 * `ConversationPageResponse`/`MessagePageResponse` do not carry `total_pages`
 * (design D3), so it is derived once here. `Math.max(1, …)` keeps an empty inbox
 * at one page instead of zero, which page navigation would have to special-case.
 */
function derivedTotalPages(total: number, perPage: number): number {
  return Math.max(1, Math.ceil(total / perPage));
}

function mapMessagingPage<T, U>(
  page: { items: T[]; page: number; per_page: number; total: number },
  mapItem: (item: T) => U,
): ConversationPage<U> {
  return {
    items: page.items.map(mapItem),
    page: page.page,
    perPage: page.per_page,
    total: page.total,
    totalPages: derivedTotalPages(page.total, page.per_page),
  };
}

function mapConversation(value: ConversationResponse): ConversationSummary {
  return {
    id: value.id,
    propertyId: value.property_id,
    guestId: value.guest_id,
    reservationId: value.reservation_id,
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

function mapMessage(value: MessageResponse): ThreadMessage {
  const metadata = value.metadata;
  return {
    id: value.id,
    conversationId: value.conversation_id,
    senderType: value.sender_type,
    senderUserId: value.sender_user_id,
    content: value.content,
    language: value.language,
    intent: value.intent,
    aiGenerated: value.ai_generated,
    confidenceScore: value.confidence_score,
    deliveryStatus: metadata?.delivery_status ?? null,
    escalationReason: metadata?.escalation_reason ?? null,
    createdAt: value.created_at,
  };
}

/**
 * Typed from the **envelope's** element rather than from `PropertyResponse`. `main`
 * split the list schema off (`PropertyListItemResponse`) while the detail kept the
 * notes, so annotating the detail here stopped compiling — and deriving from
 * `PropertyPageResponse` is what keeps this honest if the list slims down again.
 * It also means the notes D2 worried about caching are not in this payload at all
 * any more: the contract enforces what the mapper used to.
 */
function mapPropertyLabel(value: PropertyListItem): PropertyLabel {
  return { id: value.id, internalCode: value.internal_code, name: value.name };
}

export class HttpConversationsSource implements ConversationsDataSource {
  constructor(private readonly client: ApiClient) {}

  async listConversations(
    _tenantId: string,
    filters: InboxFilters,
    page: number,
    perPage: number,
  ): Promise<ConversationPage<ConversationSummary>> {
    const response = await this.client.request("/api/v1/conversations", {
      method: "GET",
      query: {
        page,
        per_page: perPage,
        ...(filters.status !== undefined ? { status: filters.status } : {}),
        ...(filters.escalationStatus !== undefined
          ? { escalation_status: filters.escalationStatus }
          : {}),
        ...(filters.propertyId !== undefined
          ? { property_id: filters.propertyId }
          : {}),
      },
    });
    return mapMessagingPage(
      response as ConversationPageResponse,
      mapConversation,
    );
  }

  async getConversation(
    _tenantId: string,
    conversationId: string,
  ): Promise<ConversationDetail> {
    const response = await this.client.request(
      "/api/v1/conversations/{conversation_id}",
      { method: "GET", pathParams: { conversation_id: conversationId } },
    );
    return mapConversation(response);
  }

  async listMessages(
    _tenantId: string,
    conversationId: string,
    page: number,
    perPage: number,
  ): Promise<ConversationPage<ThreadMessage>> {
    const response = await this.client.request(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        method: "GET",
        pathParams: { conversation_id: conversationId },
        query: { page, per_page: perPage },
      },
    );
    return mapMessagingPage(response as MessagePageResponse, mapMessage);
  }

  async createMessage(
    _tenantId: string,
    conversationId: string,
    message: NewMessage,
  ): Promise<ThreadMessage> {
    const response = await this.client.request(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        method: "POST",
        pathParams: { conversation_id: conversationId },
        body: {
          content: message.content,
          ...(message.senderType !== undefined
            ? { sender_type: message.senderType }
            : {}),
        },
      },
    );
    return mapMessage(response as MessageResponse);
  }

  async escalate(
    _tenantId: string,
    conversationId: string,
  ): Promise<ConversationDetail> {
    const response = await this.client.request(
      "/api/v1/conversations/{conversation_id}/escalate",
      { method: "POST", pathParams: { conversation_id: conversationId } },
    );
    return mapConversation(response);
  }

  async resolve(
    _tenantId: string,
    conversationId: string,
  ): Promise<ConversationDetail> {
    const response = await this.client.request(
      "/api/v1/conversations/{conversation_id}/resolve",
      { method: "POST", pathParams: { conversation_id: conversationId } },
    );
    return mapConversation(response);
  }

  /**
   * `PropertyPageResponse` is the other envelope in the same contract: `data`
   * and a real `total_pages` (design D3), so neither is synthesized here.
   */
  async listPropertyLabels(
    _tenantId: string,
  ): Promise<ConversationPage<PropertyLabel>> {
    const response = (await this.client.request("/api/v1/properties", {
      method: "GET",
      query: { page: 1, per_page: PROPERTY_LABELS_PER_PAGE },
    })) as PropertyPageResponse;
    return {
      items: response.data.map(mapPropertyLabel),
      page: response.page,
      perPage: response.per_page,
      total: response.total,
      totalPages: response.total_pages,
    };
  }
}
