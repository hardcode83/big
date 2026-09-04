"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { LoadingState } from "@/components/states";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";

import type { ConversationFilters } from "../../data";
import { mapConversationsError } from "../../lib/error-mapping";
import { escalationTone } from "../../lib/escalation-tone";
import { useConversations } from "../../hooks/use-conversations";
import { ConversationsFilters } from "./conversations-filters";

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
    return <LoadingState label={t("states:loading.label", { ns: "states" })} />;
  }
  if (state.kind === "forbidden") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("conversations:fields.forbidden")}</p>;
  }
  if (state.kind === "validation") {
    return <p className="p-4 text-body-base text-muted-foreground">{t("conversations:fields.validation")}</p>;
  }
  if (state.kind === "not-found" || state.kind === "error") {
    return (
      <div role="alert" className="flex flex-col gap-2 p-4">
        <p className="text-body-lg font-semibold text-foreground">{t("states:error.title", { ns: "states" })}</p>
        <p className="text-body-base text-muted-foreground">{t("states:error.description", { ns: "states" })}</p>
        <button
          type="button"
          className="tap-target self-start rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground"
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
    setFilters((prev) => ({ ...prev, page: state.data.page - 1 }));
  };
  const onNext = () => {
    if (isLastPage) return;
    setFilters((prev) => ({ ...prev, page: state.data.page + 1 }));
  };

  return (
    <section aria-labelledby="conversations-heading" className="flex flex-col gap-4 p-4">
      <h1 id="conversations-heading" className="text-xl font-semibold text-foreground">
        {t("navigation:routes.conversations.title", { ns: "navigation" })}
      </h1>
      <ConversationsFilters value={filters} onChange={setFilters} />
      {state.data.items.length === 0 ? (
        <>
          <p className="text-body-lg font-semibold text-foreground">{t("states:empty.title", { ns: "states" })}</p>
          <p className="text-body-base text-muted-foreground">{t("states:empty.description", { ns: "states" })}</p>
        </>
      ) : (
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("conversations:fields.channel")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("conversations:fields.status")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("conversations:fields.escalationStatus")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("conversations:fields.lastMessageAt")}
                </th>
                <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                  {t("conversations:fields.createdAt")}
                </th>
              </tr>
            </thead>
            <tbody className="font-mono text-data-mono">
              {state.data.items.map((row) => (
                <tr key={row.id} className="border-b border-border last:border-b-0 hover:bg-accent/50 transition-colors">
                  <td className="px-4 py-3 font-sans text-body-base">
                    <Link
                      href={`/conversations/${row.id}`}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {t(`conversations:channel.${row.channel}`)}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-sans text-body-base">{t(`conversations:status.${row.status}`)}</td>
                  <td className="px-4 py-3 font-sans text-body-base">
                    <span
                      className={TONE_BADGE_CLASS[escalationTone(row.escalationStatus)]}
                    >
                      {t(
                        `conversations:escalationStatus.${row.escalationStatus}`,
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">{formatDateTime(row.lastMessageAt)}</td>
                  <td className="px-4 py-3 whitespace-nowrap">{formatDateTime(row.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
      <nav aria-label={t("conversations:fields.status")} className="flex items-center gap-2">
        <button
          type="button"
          className="tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
          onClick={onPrev}
          disabled={isFirstPage}
          aria-label={t("conversations:fields.prevPage")}
        >
          {t("conversations:fields.prevPage")}
        </button>
        <button
          type="button"
          className="tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
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