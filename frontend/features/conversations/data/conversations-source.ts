import type {
  ConversationDetail,
  ConversationPage,
  ConversationSummary,
  InboxFilters,
  NewMessage,
  PropertyLabel,
  ThreadMessage,
} from "./dto";

/**
 * The conversations inbox data-access boundary (R7.1). Components, hooks and
 * stores depend ONLY on this interface, resolved through the single composition
 * point in `data/index.ts`; the only implementation is `HttpConversationsSource`.
 *
 * `tenantId` is explicit in every signature, as in `DashboardDataSource`, so
 * tenant-scoped query keys and the HTTP layer stay honest. The backend remains
 * the authority for tenant isolation.
 *
 * `POST /api/v1/conversations` (open a conversation) is deliberately absent: the
 * inbox attends threads that already exist (proposal, Out of scope).
 *
 * Methods reject with `ApiError` (lib/api) on failure.
 */
export interface ConversationsDataSource {
  /** `GET /api/v1/conversations` — the inbox, in the order the backend returns. */
  listConversations(
    tenantId: string,
    filters: InboxFilters,
    page: number,
    perPage: number,
  ): Promise<ConversationPage<ConversationSummary>>;

  /** `GET /api/v1/conversations/{id}` — 404 for an unknown or foreign conversation. */
  getConversation(
    tenantId: string,
    conversationId: string,
  ): Promise<ConversationDetail>;

  /** `GET /api/v1/conversations/{id}/messages` — chronological ascending. */
  listMessages(
    tenantId: string,
    conversationId: string,
    page: number,
    perPage: number,
  ): Promise<ConversationPage<ThreadMessage>>;

  /** `POST /api/v1/conversations/{id}/messages` — reply, or transcribe a guest message. */
  createMessage(
    tenantId: string,
    conversationId: string,
    message: NewMessage,
  ): Promise<ThreadMessage>;

  /** `POST /api/v1/conversations/{id}/escalate` — no body; 409 when already escalated. */
  escalate(
    tenantId: string,
    conversationId: string,
  ): Promise<ConversationDetail>;

  /** `POST /api/v1/conversations/{id}/resolve` — no body. */
  resolve(tenantId: string, conversationId: string): Promise<ConversationDetail>;

  /** `GET /api/v1/properties` — one cached query that labels every row (R1.7). */
  listPropertyLabels(tenantId: string): Promise<ConversationPage<PropertyLabel>>;
}
