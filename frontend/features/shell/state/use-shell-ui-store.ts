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
  toggleSidebar: (profile: ShellProfile) => void;
  setSidebarCollapsed: (profile: ShellProfile, collapsed: boolean) => void;
  setTabletNavOpen: (open: boolean) => void;
  setMobileMoreOpen: (open: boolean) => void;
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
      closeOverlays: () => set({ tabletNavOpen: false, mobileMoreOpen: false }),
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
