"use client";

import { useShellUiStore } from "./use-shell-ui-store";

/**
 * The notifications panel's open state, published for the feature that owns the panel.
 *
 * It exists because two things are both true: the shell owns the ephemeral overlay flags — so
 * that `OverlayAutoCloser` can close every one of them on a pathname change, which is what
 * makes `notifications-inbox-web` D9's "a link closes the panel with no code of its own" work —
 * and the panel itself lives in `features/notifications`, which the ESLint boundary
 * (`eslint.config.mjs`, design D2) forbids from reaching into `features/shell`'s internals.
 *
 * So the slot is published here, narrowly, instead of the other feature deep-importing the
 * store. It is the seam the `BottomNavigation → MoreMenu` precedent achieves with props; props
 * are not available here because the three shells are async Server Components and cannot read
 * a client store to pass one down.
 *
 * It exposes the panel slot and nothing else: no sidebar preference, no other overlay.
 */
export interface NotificationsPanelState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export function useNotificationsPanel(): NotificationsPanelState {
  const open = useShellUiStore((state) => state.notificationsOpen);
  const setOpen = useShellUiStore((state) => state.setNotificationsOpen);
  return { open, setOpen };
}
