"use client";

import { useTranslation } from "react-i18next";
import { Settings2 } from "lucide-react";

import type { Theme } from "@/lib/config/constants";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { LocaleSwitcher } from "./locale-switcher";
import { ThemeSwitcher } from "./theme-switcher";

/**
 * The narrow-viewport home of the two PREFERENCE controls
 * (`shell-topbar-overflow-360`, design D1/D2, R2.1-R2.2).
 *
 * Below the `sm` breakpoint the topbar cannot hold five controls at 360px — the
 * `end` slot alone claims ≥265px of it, and none of them MAY shrink, because
 * 44×44px is guaranteed in writing (`design-system-tokens.md:31`, `:45` and
 * `frontend-foundation.md:28`). «May» is the whole point: they shrink very
 * happily unless a `tap-target` floor stops them, which is what section 6
 * measured and D5 records. So the fix is to regroup rather than to
 * shrink, and what moves is the two controls that display no state: the theme
 * and the language. The notification bell shows the unread badge and the user
 * menu shows who is signed in, so both stay in the bar in either layout (D1).
 *
 * **A `Sheet` and not a `DropdownMenu`** (D2): a Radix dropdown implements the
 * *menu* pattern — roving tabindex, `role="menuitem"` children — and
 * `ThemeSwitcher` is a `role="group"` of three `aria-pressed` buttons while
 * `LocaleSwitcher` is an action button with a tooltip. Putting them in a menu
 * would break the keyboard semantics and contradict R2.2, which requires the
 * same accessible name and the same effect as in the full bar. A sheet is a
 * dialog: it takes arbitrary interactive content and brings the focus trap,
 * `Escape` and focus return that `frontend-foundation.md:28` requires of
 * drawers. It adds no dependency — `@radix-ui/react-dialog` is already here,
 * and `more-menu.tsx` already uses this same primitive with `side="bottom"`.
 *
 * **`Settings2` and not an ellipsis** (D8): «…» already means «more
 * destinations» in the bottom navigation (`more-menu.tsx`), and reusing it for
 * preferences would conflate two different things on the same screen.
 *
 * Uncontrolled `open`, unlike `MoreMenu`: that one is store-driven so overlays
 * close on navigation, and nothing in here navigates — `LocaleSwitcher` calls
 * `router.refresh()`, which re-runs the Server Components of the current route
 * without leaving it. Radix unmounting the content on close is a small bonus
 * (D4): the inner `ThemeSwitcher` is born fresh on every opening, so the two
 * instances only coexist while the sheet is open.
 *
 * `className` is how the caller hands it its media query (`sm:hidden`); the
 * component itself takes no position on when it applies (D3).
 */
export function TopbarOverflowSheet({
  initial,
  className,
}: {
  initial: Theme | null;
  className?: string;
}) {
  const { t } = useTranslation("navigation");

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          // `size="icon"` is already `h-11 w-11` (44px); `tap-target` states the
          // R3.1 guarantee explicitly, as the other topbar controls do, so it
          // survives a change to the primitive's icon size.
          className={cn("tap-target", className)}
          aria-label={t("topbarPreferences.trigger")}
        >
          <Settings2 aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="bottom" closeLabel={t("closeMenu")}>
        <SheetHeader>
          <SheetTitle>{t("topbarPreferences.title")}</SheetTitle>
        </SheetHeader>
        <div className="flex items-center gap-2">
          <ThemeSwitcher initial={initial} />
          {/* Decorative, exactly as in the wide branch: it separates two
            * unrelated controls, and announcing a divider between them would add
            * noise rather than orientation. */}
          <Separator orientation="vertical" className="mx-1 h-6" />
          <LocaleSwitcher />
        </div>
      </SheetContent>
    </Sheet>
  );
}
