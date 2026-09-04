import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import * as dataModule from "../data";
import { CreateUserForm } from "./create-user-form";

const createUserMock = vi.fn();
vi.spyOn(dataModule, "getPlatformDataSource").mockImplementation(
  () =>
    ({
      createUserInTenant: createUserMock,
    }) as unknown as ReturnType<typeof dataModule.getPlatformDataSource>,
);

const CREATED = {
  temporaryPassword: "temp-pass-123",
  user: {
    id: "u1",
    tenantId: "t1",
    name: "Persona Nueva",
    email: "new@example.com",
    role: "PROPERTY_MANAGER" as const,
    status: "ACTIVE" as const,
    phone: null,
    preferredLanguage: "es",
    lastLoginAt: null,
    createdAt: "2026-09-04T10:00:00Z",
    updatedAt: "2026-09-04T10:00:00Z",
  },
};

function renderForm(tenantId = "t1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<CreateUserForm tenantId={tenantId} />, { wrapper: Wrapper });
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("Nombre completo"), {
    target: { value: "Persona Nueva" },
  });
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: "new@example.com" },
  });
}

describe("CreateUserForm (R4.1, R4.2, R4.3, R4.5, design D5, D6)", () => {
  beforeEach(() => {
    createUserMock.mockReset();
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("submits full_name/email/phone/role scoped to the given tenantId", async () => {
    createUserMock.mockResolvedValue(CREATED);
    renderForm("t1");
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() => expect(createUserMock).toHaveBeenCalledTimes(1));
    expect(createUserMock).toHaveBeenCalledWith("t1", {
      fullName: "Persona Nueva",
      email: "new@example.com",
      phone: null,
      role: "PROPERTY_MANAGER",
    });
  });

  it("restricts the role selector to the four grantable roles, never SUPER_ADMIN", () => {
    renderForm();
    const select = screen.getByLabelText("Rol") as HTMLSelectElement;
    const options = Array.from(select.options).map((option) => option.value);

    expect(options).toEqual([
      "TENANT_OWNER",
      "PROPERTY_MANAGER",
      "CLEANER",
      "TECHNICIAN",
    ]);
    expect(options).not.toContain("SUPER_ADMIN");
  });

  it("on success switches to TemporaryPasswordReveal with the returned password", async () => {
    createUserMock.mockResolvedValue(CREATED);
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() => expect(screen.getByText("temp-pass-123")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Crear cuenta" })).not.toBeInTheDocument();
  });

  it("shows per-field errors from a 422 response", async () => {
    createUserMock.mockRejectedValue(
      new ApiError({
        code: "VALIDATION_ERROR",
        message: "Invalid request",
        status: 422,
        details: {
          errors: [
            { loc: ["body", "email"], type: "value_error", msg: "not a valid email" },
          ],
        },
      }),
    );
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() =>
      expect(screen.getByText("not a valid email")).toBeInTheDocument(),
    );
  });

  it("attributes a 409 (email already in use) to the email field", async () => {
    createUserMock.mockRejectedValue(
      new ApiError({
        code: "CONFLICT",
        message: "That email address is already in use",
        status: 409,
      }),
    );
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "Crear cuenta" }));

    await waitFor(() =>
      expect(
        screen.getByText("That email address is already in use"),
      ).toBeInTheDocument(),
    );
  });
});
