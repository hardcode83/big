import type { ReactNode } from "react";

import { LocaleSwitcher } from "./locale-switcher";

/**
 * Topbar landmark (design D6). Server Component container: `start` carries
 * context (brand, nav trigger, breadcrumbs or page title) and `end` defaults to
 * the locale switcher (a client island). The container itself ships no client JS.
 */
export function Topbar({ start, end }: { start?: ReactNode; end?: ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-background px-4">
      <div className="flex min-w-0 items-center gap-3">{start}</div>
      <div className="flex items-center gap-2">{end ?? <LocaleSwitcher />}</div>
    </header>
  );
}
