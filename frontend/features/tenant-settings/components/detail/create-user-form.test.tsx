import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { fireEvent, render, screen } from "@/test/render";

const useCreateUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-create-user", () => ({
  useCreateUser: useCreateUserMock,
}));

import { CreateUserForm } from "./create-user-form";

function fillForm() {
  fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Persona Nueva" } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
}

describe("CreateUserForm (R2.1, R2.2)", () => {
  const mutate = vi.fn();
  beforeEach(() => {
    mutate.mockReset();
  });

  it("restricts the role selector to the four grantable roles, never SUPER_ADMIN", () => {
    useCreateUserMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(<CreateUserForm />);
    const select = screen.getByLabelText("Role") as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.value);
    expect(options).toEqual(["TENANT_OWNER", "PROPERTY_MANAGER", "CLEANER", "TECHNICIAN"]);
    expect(options).not.toContain("SUPER_ADMIN");
  });

  it("submits name/email/phone/role", () => {
    useCreateUserMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(<CreateUserForm />);
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Create user" }));

    expect(mutate).toHaveBeenCalledWith({
      name: "Persona Nueva",
      email: "new@example.com",
      phone: null,
      role: "PROPERTY_MANAGER",
    });
  });

  it("attributes a 409 (email already in use) to the email field (R2.2)", () => {
    useCreateUserMock.mockReturnValue({
      mutate,
      isPending: false,
      isSuccess: false,
      isError: true,
      error: new ApiError({
        code: "CONFLICT",
        message: "That email address is already in use",
        status: 409,
      }),
    });
    render(<CreateUserForm />);
    expect(screen.getByText("That email address is already in use")).toBeInTheDocument();
  });

  it("disables the submit button while the mutation is pending", () => {
    useCreateUserMock.mockReturnValue({ mutate, isPending: true, isError: false, isSuccess: false });
    render(<CreateUserForm />);
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
  });

  it("keeps a natural keyboard focus order: full name first, submit button reachable", () => {
    useCreateUserMock.mockReturnValue({ mutate, isPending: false, isError: false, isSuccess: false });
    render(<CreateUserForm />);
    const fullName = screen.getByLabelText("Full name");
    fullName.focus();
    expect(fullName).toHaveFocus();

    const submit = screen.getByRole("button", { name: "Create user" });
    expect(submit.tabIndex).toBeGreaterThanOrEqual(0);
    submit.focus();
    expect(submit).toHaveFocus();
  });

  it("on success switches to TemporaryPasswordReveal with the returned password (R2.1)", () => {
    useCreateUserMock.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: {
        temporaryPassword: "temp-pass-123",
        user: { id: "u1", name: "Persona Nueva" },
      },
    });
    render(<CreateUserForm />);
    expect(screen.getByText("temp-pass-123")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create user" })).not.toBeInTheDocument();
  });
});
