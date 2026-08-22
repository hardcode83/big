"use client";

import { useCallback, useEffect, useState } from "react";
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

  // Unsent reply drafts, per conversation, owned **here** because this component sits
  // above the boundary that keys the thread (D22). Component state rather than a
  // module-level store on purpose: a draft is prose addressed to one tenant's guest,
  // and a singleton keyed by conversation id would outlive a same-tab session switch.
  //
  // Stored **with the tenant they were written under** and derived during render —
  // the same idiom the composer uses for `lastSent` and the thread for its page — so
  // a session switch drops them without an effect that would have to fire after one
  // render had already handed the previous tenant's prose to the new one.
  const [drafts, setDrafts] = useState<{
    tenantId: string | undefined;
    byConversation: Record<string, string>;
  }>({ tenantId, byConversation: {} });
  const currentDrafts =
    drafts.tenantId === tenantId ? drafts.byConversation : {};
  const setDraft = useCallback(
    (conversationId: string, next: string) => {
      setDrafts((current) => ({
        tenantId,
        byConversation: {
          ...(current.tenantId === tenantId ? current.byConversation : {}),
          [conversationId]: next,
        },
      }));
    },
    [tenantId],
  );

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
            {/*
              Keyed by the conversation on purpose. Selecting another thread that is
              already cached does NOT unmount this subtree — `useConversation` has no
              `placeholderData`, so there is no pending early return to remount it —
              and three separate pieces of per-conversation state turned out
              mis-scoped for that one reason: the composer's draft, its `lastSent`
              guard, and the send mutation's own error state, which is React Query
              state on the hook instance and cannot be derived away in render.
              The key resets all three at once (review 2026-08-21/22).

              The components keep their own per-conversation derivations anyway: a
              component that is only correct while its parent remembers a key is a
              trap, and the draft's failure mode — a reply delivered to the wrong
              guest — is severe enough to deserve two barriers.
            */}
            <ConversationThread
              key={selectedId}
              conversationId={selectedId}
              draft={currentDrafts[selectedId] ?? ""}
              onDraftChange={(next) => setDraft(selectedId, next)}
            />
          </>
        )}
      </div>
    </div>
  );
}
