import type { Theme } from "@/lib/config/constants";
import { Separator } from "@/components/ui/separator";
import { LocaleSwitcher } from "./locale-switcher";
import { ThemeSwitcher } from "./theme-switcher";
import { TopbarOverflowSheet } from "./topbar-overflow-sheet";

/**
 * The two preference controls, in whichever of the two layouts fits
 * (`shell-topbar-overflow-360`, design D3/D4; R1.1, R2.1, R4.1-R4.3).
 *
 * Both branches are in the DOM and **CSS chooses between them**: `hidden sm:flex`
 * on the wide one, `sm:hidden` on the sheet. That is what R4.1 requires —
 * «mediante media queries de CSS, nunca mediante detección de viewport en
 * JavaScript» — and it is the mechanism `frontend-foundation.md:23` already
 * fixes for the shell's responsive surfaces; `workspace-shell.tsx` picks between
 * `Breadcrumbs` and `PageTitle` the same way.
 *
 * **Why `hidden` and not `invisible`, `opacity-0` or `sr-only`**: R4.2 requires
 * that at any width assistive technology finds exactly ONE instance of each
 * control. Tailwind's `hidden` compiles to `display: none`, which removes the
 * subtree from the accessibility tree *and* from the tab order. The other three
 * hide from sight only, leaving a second «Tema» group and a second language
 * button that a screen reader would announce and Tab would stop at. The
 * structural guard in `test/topbar-overflow.test.ts` pins this, because it is the
 * kind of substitution that looks equivalent in a review and is not.
 *
 * A Server Component with no `"use client"`: it composes client islands but is
 * not one, which is what keeps R4.3 true — `"use client"` stays confined to the
 * controls and to `TopbarOverflowSheet`, exactly as `frontend-foundation.md:15`
 * describes. `initial` is the server-resolved theme, threaded through to both
 * branches so the correct button is pressed in the first paint.
 *
 * This component is also what makes the fix reach `PublicShell` and `GuestShell`:
 * `Topbar` uses it as its default `end` slot (D0), so the two public
 * compositions get the narrow layout without either shell being touched.
 */
export function TopbarPreferences({ initial }: { initial: Theme | null }) {
  return (
    <>
      <div className="hidden items-center gap-2 sm:flex">
        <ThemeSwitcher initial={initial} />
        {/* Decorative: it separates two unrelated controls, and announcing a
          * divider between them would add noise, not orientation. */}
        <Separator orientation="vertical" className="mx-1 h-6" />
        <LocaleSwitcher />
      </div>
      <TopbarOverflowSheet initial={initial} className="sm:hidden" />
    </>
  );
}
