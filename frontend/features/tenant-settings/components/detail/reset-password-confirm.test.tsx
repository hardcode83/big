import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";

const useResetPasswordMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-reset-password", () => ({
  useResetPassword: useResetPasswordMock,
}));

import { ResetPasswordConfirm } from "./reset-password-confirm";

describe("ResetPasswordConfirm (R4.1)", () => {
  const mutate = vi.fn();

  beforeEach(() => {
    mutate.mockReset();
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("calls the mutation with the user id on confirm", () => {
    useResetPasswordMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(
      <ResetPasswordConfirm userId="user-1" userName="Marta" open onOpenChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Reset password" }));
    expect(mutate).toHaveBeenCalledWith("user-1");
  });

  it("on success renders TemporaryPasswordReveal with the returned password (R4.1)", () => {
    useResetPasswordMock.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { temporaryPassword: "temp-pass-xyz", user: { id: "user-1", name: "Marta" } },
    });
    render(
      <ResetPasswordConfirm userId="user-1" userName="Marta" open onOpenChange={vi.fn()} />,
    );
    expect(screen.getByText("temp-pass-xyz")).toBeInTheDocument();
  });

  it("renders nothing (dialog body) while closed", () => {
    useResetPasswordMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(
      <ResetPasswordConfirm userId="user-1" userName="Marta" open={false} onOpenChange={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Reset password" })).not.toBeInTheDocument();
  });

  it("disables the confirm button while the reset is pending", () => {
    useResetPasswordMock.mockReturnValue({ mutate, isPending: true, isError: false, isSuccess: false });
    render(
      <ResetPasswordConfirm userId="user-1" userName="Marta" open onOpenChange={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Resetting…" })).toBeDisabled();
  });

  it("keeps Cancel and the confirm button reachable in keyboard tab order", () => {
    useResetPasswordMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(
      <ResetPasswordConfirm userId="user-1" userName="Marta" open onOpenChange={vi.fn()} />,
    );
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = screen.getByRole("button", { name: "Reset password" });
    for (const control of [cancel, confirm]) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(control).toHaveFocus();
    }
  });

  it("gives both footer buttons the 44px `tap-target` floor (design D14)", () => {
    useResetPasswordMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(
      <ResetPasswordConfirm userId="user-1" userName="Marta" open onOpenChange={vi.fn()} />,
    );
    // `AlertDialogCancel`/`AlertDialogAction` render the shared `Button`
    // internally: this asserts the class survives that indirection instead of
    // being dropped, leaving the buttons at the `default` size's 40px.
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("tap-target");
    expect(screen.getByRole("button", { name: "Reset password" })).toHaveClass("tap-target");
  });
});
