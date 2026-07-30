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
  footer,
  children,
}: {
  skipLink: ReactNode;
  topbar?: ReactNode;
  sidebar?: ReactNode;
  bottomNavigation?: ReactNode;
  /**
   * Persistent chrome below the content. Optional so each shell decides whether it
   * has one — the guest portal deliberately does not (change app-version-visibility,
   * R3.7). Server-rendered like the rest of the frame.
   */
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col">
      <OverlayAutoCloser />
      {skipLink}
      <div className="flex flex-1">
        {sidebar}
        {/*
          The `pb-16 md:pb-0` lives on THIS column, not on `main`. It reserves the
          space that `BottomNavigation` occupies on mobile (`fixed inset-x-0 bottom-0`),
          and reserving it here is what keeps the footer above the fixed bar instead of
          underneath it. With the padding on `main`, a footer rendered after it would
          land inside the overlaid strip and be unreadable on a phone.
        */}
        <div className="flex min-w-0 flex-1 flex-col pb-16 md:pb-0">
          {topbar}
          <main
            id="main-content"
            tabIndex={-1}
            className="flex-1 focus:outline-none"
          >
            {children}
          </main>
          {footer}
        </div>
      </div>
      {bottomNavigation}
    </div>
  );
}
