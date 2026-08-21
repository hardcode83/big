"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { InboxFilters } from "../data/dto";
import {
  useConversationList,
  usePropertyLabels,
} from "../hooks/use-conversations";
import { isForbidden } from "../lib/errors";
import { useInboxFiltersStore } from "../state/use-inbox-filters-store";
import { InboxRow } from "./inbox-row";
import { PageNav } from "./page-nav";

export interface InboxListProps {
  selectedId: string | null;
  onSelect: (conversationId: string) => void;
}

/**
 * The inbox list (R1.1, R1.4, R1.5, R1.6). Rows render **in the order the backend
 * returns them** — it orders by `last_message_at` descending with nulls last, and
 * re-sorting here would fight it.
 *
 * A 403 is its own state with no retry button (design D17): `retryPolicy` will not
 * re-request a 4xx, so offering the button would invite pressing something that
 * cannot work. Every other failure gets the shared error state with a retry that
 * really re-runs the query.
 */
export function InboxList({ selectedId, onSelect }: InboxListProps) {
  const { t } = useTranslation("conversations");
  const { t: tStates } = useTranslation("states");
  const { status, escalationStatus, propertyId, page, setPage } =
    useInboxFiltersStore();
  const labels = usePropertyLabels();

  const filters: InboxFilters = {
    ...(status !== undefined ? { status } : {}),
    ...(escalationStatus !== undefined ? { escalationStatus } : {}),
    ...(propertyId !== undefined ? { propertyId } : {}),
  };
  const query = useConversationList(filters, page);

  if (query.isPending) {
    return <LoadingState label={t("inbox.loading")} />;
  }

  if (query.isError) {
    if (isForbidden(query.error)) {
      return (
        <ErrorState
          title={t("inbox.forbidden.title")}
          description={t("inbox.forbidden.description")}
        />
      );
    }
    return (
      <ErrorState
        title={t("inbox.error.title")}
        description={t("inbox.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  const { items, page: currentPage, totalPages } = query.data;

  if (items.length === 0) {
    return (
      <EmptyState
        title={t("inbox.empty.title")}
        description={t("inbox.empty.description")}
      />
    );
  }

  const propertyById = new Map(
    (labels.data?.items ?? []).map((property) => [property.id, property]),
  );

  return (
    <div className="flex flex-col gap-3">
      <ul aria-label={t("inbox.list")} className="flex flex-col gap-2">
        {items.map((conversation) => (
          <InboxRow
            key={conversation.id}
            conversation={conversation}
            property={
              conversation.propertyId === null
                ? undefined
                : propertyById.get(conversation.propertyId)
            }
            isSelected={conversation.id === selectedId}
            onSelect={onSelect}
          />
        ))}
      </ul>
      <PageNav
        page={currentPage}
        totalPages={totalPages}
        onPageChange={setPage}
      />
    </div>
  );
}
