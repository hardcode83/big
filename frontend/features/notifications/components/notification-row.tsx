"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import type { ShellProfile } from "@/features/shell";

import type { NotificationDto } from "../data";
import { formatNotificationDate } from "../lib/format";
import { notificationCopyKey } from "../lib/notification-copy";
import { notificationHref } from "../lib/notification-destinations";

/**
 * One row of the inbox (R4.2, R4.3, R4.4, R5.1, R6.1, R6.3).
 *
 * **The text comes from `notification_type`, never from `subject`/`body`** (R4.2) — those are
 * written in English, for an operator, and carry raw UUIDs. They are not even on the DTO, so
 * this component could not paint them if it tried. An unknown type falls to the translated
 * generic and the row still renders (R4.3).
 *
 * The row links only where a live page exists (R6.1/R6.2, via the single destinations table),
 * and when it does not, it renders as plain text — never as the id (R6.3).
 *
 * Opening an unread row acknowledges it (R5.1). That happens for the link and for the
 * non-linking row alike: reading is reading, whether or not there is somewhere to go.
 */
export function NotificationRow({
  notification,
  profile,
  onOpen,
}: {
  notification: NotificationDto;
  profile: ShellProfile;
  onOpen: (id: string) => void;
}) {
  const { t, i18n } = useTranslation("notifications");
  const unread = notification.readAt === null;
  const href = notificationHref(
    profile,
    notification.relatedType,
    notification.relatedId,
  );

  const body = (
    <>
      <span className="flex items-start gap-2">
        {unread ? (
          <span
            aria-hidden="true"
            className="mt-1.5 size-2 shrink-0 rounded-full bg-primary"
          />
        ) : (
          <span aria-hidden="true" className="mt-1.5 size-2 shrink-0" />
        )}
        <span className={cn("text-sm", unread && "font-medium")}>
          {t(notificationCopyKey(notification.type))}
        </span>
      </span>
      <time
        dateTime={notification.createdAt}
        className="ml-4 block pl-2 text-xs text-muted-foreground"
      >
        {formatNotificationDate(notification.createdAt, i18n.language)}
      </time>
      {unread ? <span className="sr-only">{t("panel.unreadBadge")}</span> : null}
    </>
  );

  const shared = "block w-full rounded-md px-2 py-2 text-left hover:bg-accent";

  if (href === null) {
    return (
      <button
        type="button"
        className={shared}
        onClick={() => {
          if (unread) onOpen(notification.id);
        }}
      >
        {body}
      </button>
    );
  }

  return (
    <Link
      href={href}
      className={shared}
      onClick={() => {
        if (unread) onOpen(notification.id);
      }}
    >
      {body}
    </Link>
  );
}
