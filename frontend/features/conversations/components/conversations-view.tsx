"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { useInboxFiltersStore } from "../state/use-inbox-filters-store";
import { ConversationThread } from "./conversation-thread";
import { InboxFilters } from "./inbox-filters";
import { InboxList } from "./inbox-list";

/** The selection lives in the URL so a thread is linkable and reloadable (R3.1). */
const CONVERSATION_PARAM = "conversation";

/**
 * The inbox and the selected thread, side by side on **one** route (design D5).
 *
 * The selection is read from `?conversation=<uuid>` and written with
 * `router.replace(..., { scroll: false })`: a link opens the same thread, a reload
 * keeps it, and neither pushes a history entry per click nor jumps the viewport.
 * Filters and page stay in Zustand (D6) — the accepted limitation is that a link
 * shares the thread, not the filter.
 *
 * The single-column collapse (D19) depends on **state, not the viewport**: with no
 * selection the list shows and the thread is hidden, and vice versa, both decided
 * by Tailwind classes. No `matchMedia`, so the render stays deterministic and
 * testable. From `lg:` up both panels are visible and the back control is not.
 */
export function ConversationsView() {
  const { t } = useTranslation("conversations");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedId = searchParams.get(CONVERSATION_PARAM);

  const { user } = useAuth();
  const tenantId = user?.tenant_id;
  const resetFilters = useInboxFiltersStore((state) => state.reset);

  // Filters belong to the tenant whose inbox they were chosen in: a `propertyId`
  // picked under one tenant means nothing under the next. The store is a
  // module-level singleton and a same-tab session switch does not reload the page,
  // so this is the only thing that clears it.
  useEffect(() => {
    resetFilters();
  }, [tenantId, resetFilters]);

  function select(conversationId: string | null): void {
    const params = new URLSearchParams(searchParams.toString());
    if (conversationId === null) {
      params.delete(CONVERSATION_PARAM);
    } else {
      params.set(CONVERSATION_PARAM, conversationId);
    }
    const query = params.toString();
    router.replace(query === "" ? pathname : `${pathname}?${query}`, {
      scroll: false,
    });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <section
        aria-label={t("inbox.title")}
        className={cn(
          "min-h-0 flex-col lg:flex lg:w-2/5 lg:border-r",
          selectedId === null ? "flex" : "hidden",
        )}
      >
        <InboxFilters />
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <InboxList selectedId={selectedId} onSelect={select} />
        </div>
      </section>

      <div
        className={cn(
          "min-h-0 flex-1 flex-col lg:flex",
          selectedId === null ? "hidden" : "flex",
        )}
      >
        {selectedId === null ? (
          <EmptyState
            title={t("thread.none.title")}
            description={t("thread.none.description")}
          />
        ) : (
          <>
            <div className="border-b p-3 lg:hidden">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => select(null)}
              >
                {t("thread.back")}
              </Button>
            </div>
            <ConversationThread conversationId={selectedId} />
          </>
        )}
      </div>
    </div>
  );
}
