import type { ReactNode } from "react";

import { getServerTheme } from "@/lib/theme/server";
import { Separator } from "@/components/ui/separator";
import { LocaleSwitcher } from "./locale-switcher";
import { ThemeSwitcher } from "./theme-switcher";

/**
 * Topbar landmark (design D6). Server Component container: `start` carries
 * context (brand, nav trigger, breadcrumbs or page title) and `end` defaults to
 * the theme and locale switchers (two client islands). The container itself ships
 * no client JS.
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
  end,
}: {
  start?: ReactNode;
  end?: ReactNode;
}) {
  const theme = await getServerTheme();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-background px-4">
      <div className="flex min-w-0 items-center gap-3">{start}</div>
      <div className="flex items-center gap-2">
        {end ?? (
          <>
            <ThemeSwitcher initial={theme} />
            {/* Decorative: it separates two unrelated controls, and announcing a
              * divider between them would add noise, not orientation. */}
            <Separator orientation="vertical" className="mx-1 h-6" />
            <LocaleSwitcher />
          </>
        )}
      </div>
    </header>
  );
}
