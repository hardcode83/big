"use client";

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useNotificationsPanel, type ShellProfile } from "@/features/shell";

import { useNotifications } from "../hooks/use-notifications";
import { useMarkAllRead } from "../hooks/use-mark-all-read";
import { useMarkRead } from "../hooks/use-mark-read";
import { mapNotificationsError } from "../lib/error-mapping";
import { NotificationRow } from "./notification-row";

const PER_PAGE = 20;

/**
 * The inbox itself: a bottom `Sheet` hung off the bell (R4.5, design D9).
 *
 * A panel rather than a route, and that is what makes R3.1 — the bell in all THREE shells —
 * cost one component instead of three: a route would have to exist three times, because each
 * route group's `AuthGuard` admits a different set of roles, and each copy would drag its own
 * descriptor, breadcrumb keys, `REAL_PAGE_ROUTE_IDS` row and `routeRegistry` entry.
 *
 * `open` is governed by the shell's store rather than by local state, so `OverlayAutoCloser`
 * closes the panel when a row navigates — which is why R6's links need no closing code of
 * their own. It reaches it through `useNotificationsPanel`, published on the shell's PUBLIC
 * boundary: the ESLint rule of design D2 forbids a feature from deep-importing another's
 * store, and `npm run lint` — which CI runs — enforces it. The `MoreMenu` precedent solves the
 * same seam with props, which is not available here because the three shells are async Server
 * Components and cannot read a client store to pass one down.
 *
 * Three explicit states (R4.5) and the "mark all" button (R5.2). Mobile-first: `side="bottom"`
 * is the same choice `MoreMenu` made, because the owner operates from a phone.
 */
export function NotificationInboxSheet({
  profile,
  children,
}: {
  profile: ShellProfile;
  children: ReactNode;
}) {
  const { t } = useTranslation("notifications");
  const { open, setOpen } = useNotificationsPanel();
  const [page, setPage] = useState(1);

  const query = useNotifications({ page, perPage: PER_PAGE });
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();

  // The three explicit states of R4.5, read straight off the query. `mapNotificationsError`
  // is deliberately NOT used here: it maps a THROWN error to an i18n key (task 5.7, for the
  // acknowledgement failures below), not a query result to a UI state.
  const list = query.data;
  const failure = markRead.error ?? markAllRead.error;
  const totalPages = list ? Math.max(1, list.totalPages) : 1;

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent
        side="bottom"
        closeLabel={t("panel.close")}
        className="max-h-[80vh] overflow-y-auto"
      >
        <SheetHeader>
          <SheetTitle>{t("panel.title")}</SheetTitle>
        </SheetHeader>

        {failure ? (
          <p role="alert" className="text-sm text-destructive">
            {t(mapNotificationsError(failure))}
          </p>
        ) : null}

        {query.isPending ? <LoadingState label={t("states.loading")} /> : null}

        {query.isError ? (
          <ErrorState
            title={t("states.errorTitle")}
            description={t("states.errorDescription")}
            retryLabel={t("states.retry")}
            onRetry={() => {
              void query.refetch();
            }}
          />
        ) : null}

        {list && list.items.length === 0 ? (
          <EmptyState
            title={t("states.emptyTitle")}
            description={t("states.emptyDescription")}
          />
        ) : null}

        {list && list.items.length > 0 ? (
          <>
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={markAllRead.isPending}
                onClick={() => markAllRead.mutate()}
              >
                {t("panel.markAllRead")}
              </Button>
            </div>
            <ul className="flex flex-col gap-1">
              {list.items.map((notification) => (
                <li key={notification.id}>
                  <NotificationRow
                    notification={notification}
                    profile={profile}
                    onOpen={(id) => markRead.mutate(id)}
                  />
                </li>
              ))}
            </ul>
            <div className="flex items-center justify-between gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("panel.previousPage")}
              </Button>
              <span className="text-xs text-muted-foreground">
                {t("panel.pageStatus", { page, totalPages })}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("panel.nextPage")}
              </Button>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
