"use client";

import { useTranslation } from "react-i18next";

import type {
  ConversationEscalationStatus,
  ConversationFilters,
  ConversationStatus,
} from "../../data";

const CONVERSATION_STATUSES: ConversationStatus[] = [
  "OPEN",
  "RESOLVED",
  "ESCALATED",
  "CLOSED",
];

const CONVERSATION_ESCALATION_STATUSES: ConversationEscalationStatus[] = [
  "NONE",
  "PENDING_HUMAN",
  "HUMAN_HANDLING",
  "RESOLVED",
];

// Stable key order for the normalized `ConversationFilters` (D4).
function buildNext(
  prev: ConversationFilters,
  patch: {
    status?: ConversationStatus;
    escalationStatus?: ConversationEscalationStatus;
  },
): ConversationFilters {
  const status = "status" in patch ? patch.status : prev.status;
  const escalationStatus =
    "escalationStatus" in patch ? patch.escalationStatus : prev.escalationStatus;
  const next: ConversationFilters = {};
  if (status !== undefined) next.status = status;
  if (escalationStatus !== undefined) next.escalationStatus = escalationStatus;
  // Reset to page 1 whenever a filter changes.
  next.page = 1;
  return next;
}

/**
 * The v1 filter bar for `/conversations` (proposal R2, design D4).
 * Controlled component: the parent owns the filters state and is
 * responsible for the query. The bar does NOT render a property picker —
 * `property_id` is out of v1 scope (D4) and a picker would force a
 * second async source.
 *
 * The keys in `next` are emitted in a fixed order
 * (`status`, `escalationStatus`, `page`, `perPage`) so two equivalent
 * renders produce the same query key (precedent: design D4).
 */
export function ConversationsFilters({
  value,
  onChange,
}: {
  value: ConversationFilters;
  onChange: (next: ConversationFilters) => void;
}) {
  const { t } = useTranslation("conversations");

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="conversations-status"
        >
          {t("fields.status")}
        </label>
        <select
          id="conversations-status"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.status ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            const status = raw ? (raw as ConversationStatus) : undefined;
            onChange(buildNext(value, { status }));
          }}
        >
          <option value="">{t("fields.status")}</option>
          {CONVERSATION_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`status.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label
          className="mb-1 block text-xs font-medium text-muted-foreground"
          htmlFor="conversations-escalation-status"
        >
          {t("fields.escalationStatus")}
        </label>
        <select
          id="conversations-escalation-status"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={value.escalationStatus ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            const escalationStatus = raw
              ? (raw as ConversationEscalationStatus)
              : undefined;
            onChange(buildNext(value, { escalationStatus }));
          }}
        >
          <option value="">{t("fields.escalationStatus")}</option>
          {CONVERSATION_ESCALATION_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`escalationStatus.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <button
        type="button"
        className="rounded-md border bg-background px-3 py-1 text-sm"
        onClick={() => onChange({})}
      >
        {t("fields.clearFilters")}
      </button>
    </div>
  );
}