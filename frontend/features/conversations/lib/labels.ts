import type {
  ConversationChannel,
  ConversationEscalationStatus,
  ConversationStatus,
  MessageSenderType,
} from "../data/dto";

/**
 * i18n keys for the four closed unions of the messaging contract (design D7),
 * within the `conversations` namespace.
 *
 * Written as exhaustive `Record<Literal, key>` maps rather than interpolated as
 * `t(`status.${value}`)`: a value added to the backend must stop compiling here
 * instead of silently rendering a missing key. That is also why the keys are
 * literal strings — the catalog parity test can only see keys that are written.
 */
export const CONVERSATION_STATUS_KEYS: Record<ConversationStatus, string> = {
  OPEN: "status.OPEN",
  RESOLVED: "status.RESOLVED",
  ESCALATED: "status.ESCALATED",
  CLOSED: "status.CLOSED",
};

export const ESCALATION_STATUS_KEYS: Record<
  ConversationEscalationStatus,
  string
> = {
  NONE: "escalationStatus.NONE",
  PENDING_HUMAN: "escalationStatus.PENDING_HUMAN",
  HUMAN_HANDLING: "escalationStatus.HUMAN_HANDLING",
  RESOLVED: "escalationStatus.RESOLVED",
};

export const CHANNEL_KEYS: Record<ConversationChannel, string> = {
  WHATSAPP: "channel.WHATSAPP",
  AIRBNB_MSG: "channel.AIRBNB_MSG",
  BOOKING_MSG: "channel.BOOKING_MSG",
  EMAIL: "channel.EMAIL",
  PHONE_TRANSCRIPT: "channel.PHONE_TRANSCRIPT",
  MANUAL: "channel.MANUAL",
};

export const SENDER_TYPE_KEYS: Record<MessageSenderType, string> = {
  GUEST: "senderType.GUEST",
  OWNER: "senderType.OWNER",
  MANAGER: "senderType.MANAGER",
  AI: "senderType.AI",
  SYSTEM: "senderType.SYSTEM",
};

/** Filter option order, so the selects do not depend on object key order. */
export const CONVERSATION_STATUSES = Object.keys(
  CONVERSATION_STATUS_KEYS,
) as ConversationStatus[];
export const ESCALATION_STATUSES = Object.keys(
  ESCALATION_STATUS_KEYS,
) as ConversationEscalationStatus[];
