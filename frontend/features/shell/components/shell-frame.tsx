import type { ReactNode } from "react";

import { OverlayAutoCloser } from "./overlay-auto-closer";

/**
 * Common responsive frame shared by every shell (design D3/D6). A Server
 * Component: it owns the static structure and the single `main` landmark, and
 * delegates the only client concern — closing overlays on navigation — to the
 * `OverlayAutoCloser` island. `skipLink`, `topbar`, `sidebar` and
 * `bottomNavigation` are passed in as slots (server chrome or client islands).
 */
export function ShellFrame({
  skipLink,
  topbar,
  sidebar,
  bottomNavigation,
  children,
}: {
  skipLink: ReactNode;
  topbar?: ReactNode;
  sidebar?: ReactNode;
  bottomNavigation?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <OverlayAutoCloser />
      {skipLink}
      <div className="flex flex-1">
        {sidebar}
        <div className="flex min-w-0 flex-1 flex-col">
          {topbar}
          <main
            id="main-content"
            tabIndex={-1}
            className="flex-1 pb-16 focus:outline-none md:pb-0"
          >
            {children}
          </main>
        </div>
      </div>
      {bottomNavigation}
    </div>
  );
}
