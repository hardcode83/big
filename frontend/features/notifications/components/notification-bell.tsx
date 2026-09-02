"use client";

import { Bell } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ShellProfile } from "@/features/shell";

import { useUnreadCount } from "../hooks/use-unread-count";
import { useNotificationsIdentity } from "../hooks/use-notifications-identity";
import { NotificationInboxSheet } from "./notification-inbox-sheet";

/**
 * The largest number the badge shows as itself. Above it the badge reads "99+" — a cap, so a
 * three- or four-digit count cannot stretch the topbar. The number lives here and the FORMAT
 * lives in the catalogue (`bell.overflowCount`), because "99+" is copy and a copy string that
 * is written into JSX is exactly what `steering/frontend.md` forbids.
 */
const MAX_BADGE_COUNT = 99;

/**
 * The topbar bell and its unread badge (R3.2, R3.5, design D16).
 *
 * **It returns `null` without a resolved session**, rather than throwing the way
 * `useIncidents` does, and that is structural rather than defensive: in
 * `app/(field)/cleaner/layout.tsx` and `app/(field)/tech/layout.tsx` the `AuthGuard` sits
 * INSIDE the shell, so this renders while the session is still resolving and again while the
 * guard is redirecting. A throw there would tear down the whole chrome of both field apps.
 *
 * The count is announced, not merely drawn (R3.5): the button's accessible name is the
 * translated label plus the unread count, so a screen reader user hears "Notificaciones, 3 sin
 * leer" instead of "Notificaciones" with a number they cannot reach. The badge itself is
 * `aria-hidden` for the same reason — announcing it twice is worse than once.
 *
 * With zero unread there is no badge at all (R3.2), and the accessible name says so.
 */
export function NotificationBell({ profile }: { profile: ShellProfile }) {
  const { t } = useTranslation("notifications");
  const identity = useNotificationsIdentity();
  const { data } = useUnreadCount();

  if (identity === null) {
    return null;
  }

  const unread = data ?? 0;
  const accessibleName =
    unread > 0
      ? `${t("bell.label")}, ${t("bell.unreadCount", { count: unread })}`
      : `${t("bell.label")}, ${t("bell.noUnread")}`;

  return (
    <NotificationInboxSheet profile={profile}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        // `tap-target` is not decoration on top of `size="icon"`, and it is the
        // one topbar control that was missing it. `h-11 w-11` sets a width; as a
        // flex item inside the topbar's `end` slot that width is only a starting
        // point, and `min-width: auto` resolves to the icon's min-content — so
        // once `shell-topbar-overflow-360` gave that slot `min-w-0`, the bell
        // was the control that absorbed the squeeze. Measured in Chromium at
        // 360px before this line existed: 22px wide on `/tech`, 25px on
        // `/cleaner`, 42px on `/dashboard`, against the 44px that R3.1 of that
        // change and `design-system-tokens.md:31` both require. `tap-target`'s
        // `min-width` is what a flex item cannot shrink past.
        className="tap-target relative"
        aria-label={accessibleName}
      >
        <Bell className="size-4" aria-hidden="true" />
        {unread > 0 ? (
          <Badge
            aria-hidden="true"
            className="absolute -right-1 -top-1 min-w-5 justify-center px-1 py-0 text-[0.625rem] leading-4"
          >
            {unread > MAX_BADGE_COUNT
              ? t("bell.overflowCount", { max: MAX_BADGE_COUNT })
              : unread}
          </Badge>
        ) : null}
      </Button>
    </NotificationInboxSheet>
  );
}
