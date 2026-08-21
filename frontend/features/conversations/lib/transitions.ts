import type { ConversationEscalationStatus, ConversationStatus } from "../data/dto";

/**
 * Which inbox actions are actionable for a conversation (design D10), read from
 * `backend/app/messaging/domain/entities.py`:
 *
 * | Action              | Enabled when                                          |
 * |---------------------|-------------------------------------------------------|
 * | Escalate            | `escalationStatus === "NONE"` **and** `status === "OPEN"` |
 * | Resolve             | `status ∈ {OPEN, ESCALATED}`                          |
 * | Reply / transcribe  | `status !== "CLOSED"`                                 |
 *
 * R5.2 named only the escalation axis; the status axis restricts too, so a
 * `RESOLVED` conversation with `escalation_status = NONE` is NOT escalatable and
 * offering it would be promising a 409.
 *
 * A closed gate carries the i18n key of its reason: D11 renders the action
 * `disabled` with an accessible reason instead of hiding it, so the reason has to
 * come from the same place as the gate.
 */
export type ActionGate =
  | { enabled: true }
  | { enabled: false; reasonKey: string };

export interface ConversationAxes {
  status: ConversationStatus;
  escalationStatus: ConversationEscalationStatus;
}

const ENABLED: ActionGate = { enabled: true };

export function escalateGate({
  status,
  escalationStatus,
}: ConversationAxes): ActionGate {
  if (escalationStatus !== "NONE" || status === "ESCALATED") {
    return { enabled: false, reasonKey: "actions.disabled.alreadyEscalated" };
  }
  if (status === "CLOSED") {
    return { enabled: false, reasonKey: "actions.disabled.conversationClosed" };
  }
  if (status === "RESOLVED") {
    return { enabled: false, reasonKey: "actions.disabled.conversationResolved" };
  }
  return ENABLED;
}

export function resolveGate({ status }: ConversationAxes): ActionGate {
  if (status === "OPEN" || status === "ESCALATED") {
    return ENABLED;
  }
  if (status === "CLOSED") {
    return { enabled: false, reasonKey: "actions.disabled.conversationClosed" };
  }
  return { enabled: false, reasonKey: "actions.disabled.alreadyResolved" };
}

/** Replying and transcribing share a gate: both are writes into the thread. */
export function writeMessageGate({ status }: ConversationAxes): ActionGate {
  if (status === "CLOSED") {
    return { enabled: false, reasonKey: "actions.disabled.conversationClosed" };
  }
  return ENABLED;
}
