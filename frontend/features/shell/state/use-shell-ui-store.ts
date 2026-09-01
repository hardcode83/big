"use client";

import { create } from "zustand";
import {
  createJSONStorage,
  persist,
  type StateStorage,
} from "zustand/middleware";

import type { ShellProfile } from "../navigation/route-registry";

/**
 * The single Zustand store for the shell (design D7). It holds only lightweight
 * UI state: the per-profile sidebar collapse preference (persisted) and ephemeral
 * overlay flags (never persisted). It stores NO locale, active route, session,
 * roles, query results, feature flags, or business data.
 *
 * Persisting the sidebar map per ShellProfile guarantees a Workspace preference
 * never affects the Cleaner or Technician shells.
 */
export interface ShellUiState {
  sidebarCollapsedByProfile: Partial<Record<ShellProfile, boolean>>;
  tabletNavOpen: boolean;
  mobileMoreOpen: boolean;
  /**
   * The notifications panel, opened from the bell in the topbar
   * (`notifications-inbox-web` design D9). Ephemeral like the other two overlays and never
   * persisted: a panel that reopened itself on the next visit would be showing yesterday's
   * inbox. It lives here rather than in the bell's own state so `OverlayAutoCloser` closes it
   * when a row navigates away — which is what makes R6's links cost no code of their own.
   *
   * It is UI state and only UI state: the counter and the rows are server state and live in
   * the `QueryClient` (`steering/frontend.md`, "No duplicar server state en stores").
   */
  notificationsOpen: boolean;
  toggleSidebar: (profile: ShellProfile) => void;
  setSidebarCollapsed: (profile: ShellProfile, collapsed: boolean) => void;
  setTabletNavOpen: (open: boolean) => void;
  setMobileMoreOpen: (open: boolean) => void;
  setNotificationsOpen: (open: boolean) => void;
  closeOverlays: () => void;
}

export const SHELL_UI_STORAGE_KEY = "autohostai.ui.shell.v1";

/** No-op storage used on the server, where there is no localStorage. */
const noopStorage: StateStorage = {
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
};

export const useShellUiStore = create<ShellUiState>()(
  persist(
    (set) => ({
      sidebarCollapsedByProfile: {},
      tabletNavOpen: false,
      mobileMoreOpen: false,
      notificationsOpen: false,
      toggleSidebar: (profile) =>
        set((state) => ({
          sidebarCollapsedByProfile: {
            ...state.sidebarCollapsedByProfile,
            [profile]: !state.sidebarCollapsedByProfile[profile],
          },
        })),
      setSidebarCollapsed: (profile, collapsed) =>
        set((state) => ({
          sidebarCollapsedByProfile: {
            ...state.sidebarCollapsedByProfile,
            [profile]: collapsed,
          },
        })),
      setTabletNavOpen: (open) => set({ tabletNavOpen: open }),
      setMobileMoreOpen: (open) => set({ mobileMoreOpen: open }),
      setNotificationsOpen: (open) => set({ notificationsOpen: open }),
      closeOverlays: () =>
        set({ tabletNavOpen: false, mobileMoreOpen: false, notificationsOpen: false }),
    }),
    {
      name: SHELL_UI_STORAGE_KEY,
      version: 1,
      // Guarded so the store is safe to import on the server (no localStorage);
      // persistence activates only in the browser.
      storage: createJSONStorage(() =>
        typeof window === "undefined" ? noopStorage : window.localStorage,
      ),
      // Only the sidebar preference map is persisted; overlays stay ephemeral.
      partialize: (state) => ({
        sidebarCollapsedByProfile: state.sidebarCollapsedByProfile,
      }),
    },
  ),
);
