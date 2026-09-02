import type { ReactNode } from "react";

import { getServerTheme } from "@/lib/theme/server";
import { TopbarPreferences } from "./topbar-preferences";

/**
 * Topbar landmark (design D6). Server Component container: `start` carries
 * context (brand, nav trigger, breadcrumbs or page title), `center` is the
 * marketing navigation slot used by `/` only (the landing passes
 * `<MarketingNav />` here, see design D3), and `end` defaults to
 * `TopbarPreferences` — the theme and locale switchers in whichever of their two
 * layouts fits the viewport. The container itself ships no client JS.
 *
 * That default is what carries the 360px overflow fix to `PublicShell` and
 * `GuestShell` (`shell-topbar-overflow-360`, D0): neither passes `end`, so
 * neither shell needed touching. It used to spell the two switchers out here.
 *
 * `async` because the theme has to be resolved on the server and handed to
 * `ThemeSwitcher` as a prop, so the right button is pressed in the first paint
 * (design D5).
 *
 * That async-ness cost one line in each of the five shells, and D5 was wrong to
 * predict otherwise. They mounted this as a JSX element (`topbar={<Topbar … />}`),
 * and a client renderer cannot resolve an async element: the whole chrome
 * disappeared and thirteen shell tests failed looking for `role="banner"`. They
 * now call and await it — `topbar={await Topbar({ start })}` — which is what this
 * repo already did for async Server Components everywhere else, so `Topbar` is
 * consistent with them rather than the exception. Correction recorded in D5 and
 * task 6.4.
 */
export async function Topbar({
  start,
  center,
  end,
}: {
  start?: ReactNode;
  center?: ReactNode;
  end?: ReactNode;
}) {
  const theme = await getServerTheme();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-background px-4">
      <div className="flex min-w-0 items-center gap-3">{start}</div>
      {center ? (
        <div className="flex min-w-0 items-center gap-3">{center}</div>
      ) : null}
      {/*
        * `min-w-0` matches the other two slots, added by
        * `shell-topbar-overflow-360` (design D5). Without it this flex item's
        * `min-width` is `auto`, which makes the `truncate max-w-48` on
        * `UserMenu`'s email inert: a long address pushes the row instead of
        * being clipped.
        *
        * It does not fix the overflow on its own, and the reason is narrower
        * than the one written here first («none of them may shrink»): a control
        * has a floor only where it declares one. Four of the five carry
        * `tap-target` (`min-width: 44px`); `NotificationBell` did not, and once
        * this slot could shrink it was the control that absorbed the squeeze —
        * measured at 22px wide on `/tech` while the row reported no overflow at
        * all. Corrected in D5 and pinned by the 44×44 block of
        * `topbar-overflow.browser.test.tsx`, because a width check alone reads
        * «regrouped» and «squeezed» identically.
        */}
      <div className="flex min-w-0 items-center gap-2">
        {end ?? <TopbarPreferences initial={theme} />}
      </div>
    </header>
  );
}
