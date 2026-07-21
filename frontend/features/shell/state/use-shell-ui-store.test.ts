import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  SHELL_UI_STORAGE_KEY,
  useShellUiStore,
} from "@/features/shell/state/use-shell-ui-store";

function reset() {
  window.localStorage.clear();
  useShellUiStore.setState({
    sidebarCollapsedByProfile: {},
    tabletNavOpen: false,
    mobileMoreOpen: false,
  });
}

describe("useShellUiStore (D7)", () => {
  beforeEach(reset);
  afterEach(reset);

  it("starts with a deterministic initial state", () => {
    const state = useShellUiStore.getState();
    expect(state.sidebarCollapsedByProfile).toEqual({});
    expect(state.tabletNavOpen).toBe(false);
    expect(state.mobileMoreOpen).toBe(false);
  });

  it("toggles a profile's sidebar without touching other profiles", () => {
    useShellUiStore.getState().toggleSidebar("workspace");
    expect(
      useShellUiStore.getState().sidebarCollapsedByProfile.workspace,
    ).toBe(true);
    expect(
      useShellUiStore.getState().sidebarCollapsedByProfile.cleaner,
    ).toBeUndefined();
  });

  it("closes all ephemeral overlays", () => {
    useShellUiStore.getState().setTabletNavOpen(true);
    useShellUiStore.getState().setMobileMoreOpen(true);
    useShellUiStore.getState().closeOverlays();
    expect(useShellUiStore.getState().tabletNavOpen).toBe(false);
    expect(useShellUiStore.getState().mobileMoreOpen).toBe(false);
  });

  it("persists only the sidebar preference map, never overlays", () => {
    useShellUiStore.getState().setSidebarCollapsed("workspace", true);
    useShellUiStore.getState().setTabletNavOpen(true);

    const persisted = JSON.parse(
      window.localStorage.getItem(SHELL_UI_STORAGE_KEY) ?? "{}",
    );
    expect(persisted.state.sidebarCollapsedByProfile).toEqual({
      workspace: true,
    });
    expect(persisted.state).not.toHaveProperty("tabletNavOpen");
    expect(persisted.state).not.toHaveProperty("mobileMoreOpen");
  });
});
