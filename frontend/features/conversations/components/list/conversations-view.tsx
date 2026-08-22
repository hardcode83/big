"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ConversationEscalationStatus, ConversationFilters } from "../../data";
import { mapConversationsError } from "../../lib/error-mapping";
import { useConversations } from "../../hooks/use-conversations";
import { ConversationsFilters } from "./conversations-filters";

const ESCALATION_BADGE: Record<ConversationEscalationStatus, string> = {
  NONE: "bg-gray-100 text-gray-700",
  PENDING_HUMAN: "bg-amber-100 text-amber-800",
  HUMAN_HANDLING: "bg-blue-100 text-blue-700",
  RESOLVED: "bg-emerald-100 text-emerald-700",
};

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return value.slice(0, 16).replace("T", " ");
}

/**
 * The list view for `/conversations` (proposal R2, design D5). Five
 * columns, no `propertyId` (D5: the endpoint returns `propertyId` as a
 * UUID and we don't resolve it to a name). Pagination uses `lastPage` in
 * the client (R2.5): `max(1, ceil(total / perPage))`.
 *
 * The view consumes `useConversations(filters)` — the filters live in
 * `useState` here, not in a Zustand store, because there is no URL
 * synchronisation in v1 and no other view reads them.
 */
export function ConversationsView() {
  const { t } = useTranslation(["conversations", "states", "navigation"]);
  const [filters, setFilters] = useState<ConversationFilters>({});
  const query = useConversations(filters);
  const state = mapConversationsError(query);

  if (state.kind === "loading") {
    return <p>{t("states:loading.label", { ns: "states" })}</p>;
  }
  if (state.kind === "forbidden") {
    return <p>{t("conversations:fields.forbidden")}</p>;
  }
  if (state.kind === "validation") {
    return <p>{t("conversations:fields.validation")}</p>;
  }
  if (state.kind === "not-found" || state.kind === "error") {
    return (
      <div>
        <p>{t("states:error.title", { ns: "states" })}</p>
        <p>{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          onClick={() => {
            void query.refetch();
          }}
        >
          {t("states:error.retry", { ns: "states" })}
        </button>
      </div>
    );
  }
  // state.kind === "ok"
  const lastPage = Math.max(1, Math.ceil(state.data.total / state.data.perPage));
  const isFirstPage = state.data.page <= 1;
  const isLastPage = state.data.page >= lastPage;
  const onPrev = () => {
    if (isFirstPage) return;
    setFilters((prev) => ({ ...prev, page: (state.data.page ?? 1) - 1 }));
  };
  const onNext = () => {
    if (isLastPage) return;
    setFilters((prev) => ({ ...prev, page: (state.data.page ?? 1) + 1 }));
  };

  return (
    <section aria-labelledby="conversations-heading">
      <h1 id="conversations-heading">
        {t("navigation:routes.conversations.title", { ns: "navigation" })}
      </h1>
      <ConversationsFilters value={filters} onChange={setFilters} />
      {state.data.items.length === 0 ? (
        <>
          <p>{t("states:empty.title", { ns: "states" })}</p>
          <p>{t("states:empty.description", { ns: "states" })}</p>
        </>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">{t("conversations:fields.channel")}</th>
              <th scope="col">{t("conversations:fields.status")}</th>
              <th scope="col">{t("conversations:fields.escalationStatus")}</th>
              <th scope="col">{t("conversations:fields.lastMessageAt")}</th>
              <th scope="col">{t("conversations:fields.createdAt")}</th>
            </tr>
          </thead>
          <tbody>
            {state.data.items.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link href={`/conversations/${row.id}`}>
                    {t(`conversations:channel.${row.channel}`)}
                  </Link>
                </td>
                <td>{t(`conversations:status.${row.status}`)}</td>
                <td>
                  <span
                    className={
                      ESCALATION_BADGE[row.escalationStatus] ??
                      "bg-gray-100 text-gray-700"
                    }
                  >
                    {t(
                      `conversations:escalationStatus.${row.escalationStatus}`,
                    )}
                  </span>
                </td>
                <td>{formatDateTime(row.lastMessageAt)}</td>
                <td>{formatDateTime(row.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <nav aria-label={t("conversations:fields.status")}>
        <button
          type="button"
          onClick={onPrev}
          disabled={isFirstPage}
          aria-label={t("conversations:fields.prevPage")}
        >
          {t("conversations:fields.prevPage")}
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={isLastPage}
          aria-label={t("conversations:fields.nextPage")}
        >
          {t("conversations:fields.nextPage")}
        </button>
      </nav>
    </section>
  );
}