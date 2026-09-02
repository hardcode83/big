import type { Theme } from "@/lib/config/constants";
import { UserMenu } from "@/features/auth";
import { NotificationBell } from "@/features/notifications";
import type { ShellProfile } from "../navigation/route-registry";
import { TopbarPreferences } from "./topbar-preferences";

/**
 * The `end` slot every authenticated shell passes to `Topbar`
 * (`shell-topbar-overflow-360`, design D3; R1.1, R2.1, R2.3, R4.3).
 *
 * Until this change, `workspace-shell.tsx`, `cleaner-shell.tsx` and
 * `technician-shell.tsx` each wrote out the same five-control fragment
 * literally — the composition `sdd/specs/frontend-foundation.md:25` fixes in
 * writing, held in three places. Three copies is why the overflow had to be
 * fixed three times, and it is what made the structural guard in
 * `test/topbar-overflow.test.ts` possible to write at all: after this there is
 * ONE place where that composition lives.
 *
 * **What stays in the bar and why** (D1): the bell and the user menu. The
 * criterion is what information is lost by hiding a control behind a tap. The
 * bell *shows state* — the unread badge (`notification-bell.tsx`) — and the user
 * menu *shows identity*, which is who has the session open on a shared device,
 * the reason written into `user-menu.tsx` itself. Neither is a preference you
 * set once. The theme and the language show nothing, so those are the two that
 * move into the sheet on narrow viewports.
 *
 * **`UserMenu` is not touched.** R2.3 requires its sign-out confirmation
 * (`AlertDialog`) and the `logout → router.replace("/") → router.refresh()`
 * sequence to survive untouched — that behaviour belongs to
 * `frontend-auth-session`, and this change only moves where the fragment is
 * written, never what it does. It stays in the bar in BOTH layouts, so nothing
 * about it changes.
 *
 * A Server Component: it composes client islands without becoming one (R4.3).
 */
export function AuthenticatedTopbarActions({
  profile,
  theme,
}: {
  profile: ShellProfile;
  theme: Theme | null;
}) {
  return (
    <>
      <TopbarPreferences initial={theme} />
      <NotificationBell profile={profile} />
      <UserMenu />
    </>
  );
}
