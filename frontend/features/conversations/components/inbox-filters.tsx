"use client";

import { useTranslation } from "react-i18next";

import type {
  ConversationEscalationStatus,
  ConversationStatus,
} from "../data/dto";
import { usePropertyLabels } from "../hooks/use-conversations";
import {
  CONVERSATION_STATUSES,
  CONVERSATION_STATUS_KEYS,
  ESCALATION_STATUSES,
  ESCALATION_STATUS_KEYS,
} from "../lib/labels";
import { useInboxFiltersStore } from "../state/use-inbox-filters-store";

const CLOSED_NOTE_ID = "inbox-status-closed-note";

/**
 * Inbox filters (R2.1, R2.2, R2.3). Options come from the exhaustive label maps,
 * so a value added to the backend cannot silently disappear from the selects; an
 * unselected filter is simply absent from the query.
 *
 * `status = CLOSED` carries a note that nothing produces that state today, so a
 * permanently empty list does not read as a failure. `escalation_status =
 * HUMAN_HANDLING` deliberately carries **no** such note: answering a thread that
 * is waiting for a person runs `take_over`, so that filter has real rows (R2.3).
 */
export function InboxFilters() {
  const { t } = useTranslation("conversations");
  const {
    status,
    escalationStatus,
    propertyId,
    setStatus,
    setEscalationStatus,
    setPropertyId,
  } = useInboxFiltersStore();
  const labels = usePropertyLabels();
  const showClosedNote = status === "CLOSED";

  return (
    <section
      aria-label={t("filters.legend")}
      className="flex flex-col gap-2 border-b p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="inbox-status">
          {t("filters.status")}
        </label>
        <select
          id="inbox-status"
          aria-describedby={showClosedNote ? CLOSED_NOTE_ID : undefined}
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={status ?? ""}
          onChange={(event) =>
            setStatus((event.target.value || undefined) as ConversationStatus)
          }
        >
          <option value="">{t("filters.status")}</option>
          {CONVERSATION_STATUSES.map((value) => (
            <option key={value} value={value}>
              {t(CONVERSATION_STATUS_KEYS[value])}
            </option>
          ))}
        </select>

        <label className="sr-only" htmlFor="inbox-escalation">
          {t("filters.escalationStatus")}
        </label>
        <select
          id="inbox-escalation"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={escalationStatus ?? ""}
          onChange={(event) =>
            setEscalationStatus(
              (event.target.value || undefined) as ConversationEscalationStatus,
            )
          }
        >
          <option value="">{t("filters.escalationStatus")}</option>
          {ESCALATION_STATUSES.map((value) => (
            <option key={value} value={value}>
              {t(ESCALATION_STATUS_KEYS[value])}
            </option>
          ))}
        </select>

        <label className="sr-only" htmlFor="inbox-property">
          {t("filters.property")}
        </label>
        <select
          id="inbox-property"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={propertyId ?? ""}
          onChange={(event) => setPropertyId(event.target.value || undefined)}
        >
          <option value="">{t("filters.property")}</option>
          {(labels.data?.items ?? []).map((property) => (
            <option key={property.id} value={property.id}>
              {property.internalCode}
            </option>
          ))}
        </select>
      </div>
      {showClosedNote ? (
        <p id={CLOSED_NOTE_ID} className="text-xs text-muted-foreground">
          {t("filters.closedNote")}
        </p>
      ) : null}
    </section>
  );
}
