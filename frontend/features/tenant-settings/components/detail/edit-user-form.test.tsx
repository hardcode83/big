import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { fireEvent, render, screen } from "@/test/render";

const useUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-user", () => ({ useUser: useUserMock }));

const useUpdateUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-update-user", () => ({ useUpdateUser: useUpdateUserMock }));

const useAuthMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ useAuth: useAuthMock }));

import { EditUserForm } from "./edit-user-form";

const USER = {
  id: "user-2",
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

describe("EditUserForm (R3.1, R3.2, R3.3)", () => {
  const mutate = vi.fn();

  beforeEach(() => {
    mutate.mockReset();
    useUserMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: USER,
      refetch: vi.fn(),
    });
    useUpdateUserMock.mockReturnValue({ mutate, isPending: false, isError: false });
    useAuthMock.mockReturnValue({ user: { id: "owner-1", role: "TENANT_OWNER" } });
  });

  it("sends only the changed fields on submit (R3.1)", () => {
    render(<EditUserForm userId="user-2" />);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Marta C." } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(mutate).toHaveBeenCalledWith(
      { userId: "user-2", input: { name: "Marta C." } },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("disables the role and status controls when the target row is the acting user's own (R3.3)", () => {
    useAuthMock.mockReturnValue({ user: { id: "user-2", role: "CLEANER" } });
    render(<EditUserForm userId="user-2" />);

    expect(screen.getByLabelText("Role")).toBeDisabled();
    expect(screen.getByLabelText("Status")).toBeDisabled();
  });

  it("leaves role/status enabled for a row that is not the acting user's own", () => {
    render(<EditUserForm userId="user-2" />);
    expect(screen.getByLabelText("Role")).not.toBeDisabled();
    expect(screen.getByLabelText("Status")).not.toBeDisabled();
  });

  it("disables the submit button while the mutation is pending", () => {
    useUpdateUserMock.mockReturnValue({ mutate, isPending: true, isError: false });
    render(<EditUserForm userId="user-2" />);
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  });

  it("keeps a natural keyboard focus order: full name first, submit button reachable", () => {
    render(<EditUserForm userId="user-2" />);
    const fullName = screen.getByLabelText("Full name");
    fullName.focus();
    expect(fullName).toHaveFocus();

    const submit = screen.getByRole("button", { name: "Save changes" });
    expect(submit.tabIndex).toBeGreaterThanOrEqual(0);
    submit.focus();
    expect(submit).toHaveFocus();
  });

  it("surfaces the backend's 422 (last-owner / self-action) with the backend's own message, no generic fallback (R3.2)", () => {
    useUpdateUserMock.mockReturnValue({
      mutate,
      isPending: false,
      isError: true,
      error: new ApiError({
        code: "VALIDATION_ERROR",
        message: "This would leave the tenant without an active owner, and there is no endpoint to appoint one from outside it",
        status: 422,
        details: {},
      }),
    });
    render(<EditUserForm userId="user-2" />);

    expect(
      screen.getByText(
        "This would leave the tenant without an active owner, and there is no endpoint to appoint one from outside it",
      ),
    ).toBeInTheDocument();
  });
});
