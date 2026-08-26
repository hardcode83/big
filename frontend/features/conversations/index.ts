export { ConversationsView } from "./components/list/conversations-view";
export { ConversationThreadView } from "./components/thread/conversation-thread-view";

export {
  useConversations,
  useConversation,
  useConversationMessages,
} from "./hooks/use-conversations";
export { useReplyToConversation } from "./hooks/use-reply-to-conversation";

export { getConversationsDataSource } from "./data";
export { mapConversationsError } from "./lib/error-mapping";
export { conversationsKeys } from "./hooks/query-keys";

export type {
  ConversationChannel,
  ConversationDetailDto,
  ConversationEscalationStatus,
  ConversationFilters,
  ConversationList,
  ConversationPagination,
  ConversationStatus,
  ConversationSummaryDto,
  MessageDto,
  MessageList,
  MessageSenderType,
} from "./data";