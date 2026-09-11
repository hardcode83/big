import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";

import type { UserDto } from "../../dto";

const useDeactivateUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-deactivate-user", () => ({
  useDeactivateUser: useDeactivateUserMock,
}));

const useActiveCleanerCountMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-active-cleaner-count", () => ({
  useActiveCleanerCount: useActiveCleanerCountMock,
}));

import { DeactivateUserConfirm } from "./deactivate-user-confirm";

const ACTIVE_CLEANER: UserDto = {
  id: "user-1",
  name: "Marta Cleaner",
  email: "marta@example.com",
  phone: null,
  preferredLanguage: "es",
  role: "CLEANER",
  status: "ACTIVE",
  lastLoginAt: null,
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
};

const ACTIVE_MANAGER: UserDto = { ...ACTIVE_CLEANER, id: "user-2", role: "PROPERTY_MANAGER" };

describe("DeactivateUserConfirm (R3.4)", () => {
  beforeEach(() => {
    useDeactivateUserMock.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false });
  });

  it("shows the last-active-cleaner warning when total === 1 for an ACTIVE CLEANER", () => {
    useActiveCleanerCountMock.mockReturnValue({ data: 1 });
    render(
      <DeactivateUserConfirm user={ACTIVE_CLEANER} open onOpenChange={vi.fn()} />,
    );
    expect(useActiveCleanerCountMock).toHaveBeenCalledWith(true);
    expect(screen.getByText(/only active cleaner/)).toBeInTheDocument();
    // Non-blocking: the confirm button is still enabled.
    expect(screen.getByRole("button", { name: "Deactivate" })).not.toBeDisabled();
  });

  it("does not show the warning when the cleaner is not the last active one", () => {
    useActiveCleanerCountMock.mockReturnValue({ data: 3 });
    render(
      <DeactivateUserConfirm user={ACTIVE_CLEANER} open onOpenChange={vi.fn()} />,
    );
    expect(screen.queryByText(/only active cleaner/)).not.toBeInTheDocument();
  });

  it("does not fire the active-cleaner-count query or show the warning for a non-cleaner row", () => {
    useActiveCleanerCountMock.mockReturnValue({ data: undefined });
    render(
      <DeactivateUserConfirm user={ACTIVE_MANAGER} open onOpenChange={vi.fn()} />,
    );
    expect(useActiveCleanerCountMock).toHaveBeenCalledWith(false);
    expect(screen.queryByText(/only active cleaner/)).not.toBeInTheDocument();
  });

  it("disables the confirm button while the deactivation is pending", () => {
    useDeactivateUserMock.mockReturnValue({ mutate: vi.fn(), isPending: true, isError: false });
    useActiveCleanerCountMock.mockReturnValue({ data: undefined });
    render(
      <DeactivateUserConfirm user={ACTIVE_MANAGER} open onOpenChange={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Deactivating…" })).toBeDisabled();
  });

  it("keeps Cancel and the confirm button reachable in keyboard tab order", () => {
    useActiveCleanerCountMock.mockReturnValue({ data: undefined });
    render(
      <DeactivateUserConfirm user={ACTIVE_MANAGER} open onOpenChange={vi.fn()} />,
    );
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Deactivate" });
    for (const control of [cancel, confirm]) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(control).toHaveFocus();
    }
  });

  it("gives both footer buttons the 44px `tap-target` floor (design D14)", () => {
    useActiveCleanerCountMock.mockReturnValue({ data: undefined });
    render(
      <DeactivateUserConfirm user={ACTIVE_MANAGER} open onOpenChange={vi.fn()} />,
    );
    // `AlertDialogCancel`/`AlertDialogAction` render the shared `Button`
    // internally: this asserts the class survives that indirection instead of
    // being dropped, leaving the buttons at the `default` size's 40px.
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("tap-target");
    expect(screen.getByRole("button", { name: "Deactivate" })).toHaveClass("tap-target");
  });
});
