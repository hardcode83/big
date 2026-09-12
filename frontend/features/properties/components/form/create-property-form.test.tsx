import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esProperties from "@/locales/es/properties.json";
import { fireEvent, render, screen, within } from "@/test/render";

const pushMock = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const useCreatePropertyMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-create-property", () => ({
  useCreateProperty: useCreatePropertyMock,
}));

import { CreatePropertyForm } from "./create-property-form";

function mutationState(
  overrides: Partial<{
    mutate: ReturnType<typeof vi.fn>;
    isPending: boolean;
    isError: boolean;
    error: unknown;
  }> = {},
) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  };
}

function renderForm() {
  return render(
    <I18nProvider locale="es">
      <CreatePropertyForm />
    </I18nProvider>,
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * `name`/`internal_code` labels carry a visible, `aria-hidden` " *" required
 * marker (UI-UX finding 1) that is not part of the translated label string —
 * matched as an anchored, optional suffix so "Nombre" cannot ambiguously
 * match the unrelated, longer "Nombre del WiFi" label.
 */
function labelMatcher(label: string): RegExp {
  return new RegExp(`^${escapeRegExp(label)}( \\*)?$`);
}

/**
 * `property-fieldset.tsx`'s per-field wrapper: each `<div className="flex
 * flex-col gap-1">` holds exactly one field's label, its `id`-bearing
 * control, and its own `FieldError` (a `role="alert"` `<p>`) — there is no
 * `aria-describedby` linking error to control, so this structural wrapper is
 * the field/error association to assert against (R1.5).
 */
function fieldWrapper(inputId: string): HTMLElement {
  const input = document.getElementById(inputId);
  if (!input) {
    throw new Error(`no element with id "${inputId}"`);
  }
  const wrapper = input.closest("div");
  if (!wrapper) {
    throw new Error(`"${inputId}" has no wrapping div`);
  }
  return wrapper;
}

function fillRequiredFields() {
  fireEvent.change(
    screen.getByLabelText(labelMatcher(esProperties.createForm.fields.name)),
    { target: { value: "Redes 11" } },
  );
  fireEvent.change(
    screen.getByLabelText(
      labelMatcher(esProperties.createForm.fields.internalCode),
    ),
    { target: { value: "REDES11" } },
  );
}

beforeEach(() => {
  pushMock.mockReset();
  useCreatePropertyMock.mockReset();
});

describe("CreatePropertyForm — happy path navigation (R1.4, design D11)", () => {
  it("submits the fields and navigates to the new property's detail page on success", () => {
    const mutate = vi.fn((_input, opts) => {
      opts?.onSuccess?.({ id: "new-property-id" });
    });
    useCreatePropertyMock.mockReturnValue(mutationState({ mutate }));
    renderForm();

    fillRequiredFields();
    fireEvent.click(
      screen.getByRole("button", { name: esProperties.createForm.submit }),
    );

    expect(mutate).toHaveBeenCalledTimes(1);
    const [input] = mutate.mock.calls[0];
    expect(input).toMatchObject({ name: "Redes 11", internalCode: "REDES11" });
    expect(pushMock).toHaveBeenCalledWith("/properties/new-property-id");
  });
});

describe("CreatePropertyForm — client-side validation blocks submit (R1.3)", () => {
  it("does not call the mutation and shows the required error for empty required fields", () => {
    const mutate = vi.fn();
    useCreatePropertyMock.mockReturnValue(mutationState({ mutate }));
    renderForm();

    fireEvent.click(
      screen.getByRole("button", { name: esProperties.createForm.submit }),
    );

    expect(mutate).not.toHaveBeenCalled();
    expect(
      screen.getAllByText(esProperties.createForm.errors.required).length,
    ).toBeGreaterThan(0);
  });

  it("does not call the mutation and shows the required error for an emptied timezone (sdd-qa finding 1)", () => {
    const mutate = vi.fn();
    useCreatePropertyMock.mockReturnValue(mutationState({ mutate }));
    renderForm();

    fillRequiredFields();
    fireEvent.change(
      screen.getByLabelText(
        labelMatcher(esProperties.createForm.fields.timezone),
      ),
      { target: { value: "" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: esProperties.createForm.submit }),
    );

    expect(mutate).not.toHaveBeenCalled();
    expect(
      screen.getByText(esProperties.createForm.errors.required),
    ).toBeInTheDocument();
  });

  it("does not call the mutation when country is not exactly 2 uppercase letters", () => {
    const mutate = vi.fn();
    useCreatePropertyMock.mockReturnValue(mutationState({ mutate }));
    renderForm();

    fillRequiredFields();
    fireEvent.change(
      screen.getByLabelText(esProperties.createForm.fields.country),
      { target: { value: "z" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: esProperties.createForm.submit }),
    );

    expect(mutate).not.toHaveBeenCalled();
    expect(
      screen.getByText(esProperties.createForm.errors.invalidCountry),
    ).toBeInTheDocument();
  });
});

describe("CreatePropertyForm — 409 conflicts attribute to the right field (R1.5)", () => {
  it("attributes a duplicate internal_code to that field, not to pms_external_id", () => {
    const message = "internal_code already exists for this tenant";
    useCreatePropertyMock.mockReturnValue(
      mutationState({
        isError: true,
        error: new ApiError({ code: "CONFLICT", message, status: 409 }),
      }),
    );
    renderForm();

    // Rendered under internal_code's own field wrapper...
    expect(
      within(fieldWrapper("property-internal-code")).getByText(message),
    ).toBeInTheDocument();
    // ...and NOT under pms_external_id's — this is what a swapped
    // `mapPropertyFieldErrors` <-> `fieldErrors` wiring would break, even
    // though the message would still appear somewhere in the document.
    expect(
      within(fieldWrapper("property-pms-external-id")).queryByText(message),
    ).not.toBeInTheDocument();
  });

  it("attributes a duplicate pms_external_id to that field, not to internal_code", () => {
    const message = "pms_external_id already exists for this tenant";
    useCreatePropertyMock.mockReturnValue(
      mutationState({
        isError: true,
        error: new ApiError({ code: "CONFLICT", message, status: 409 }),
      }),
    );
    renderForm();

    expect(
      within(fieldWrapper("property-pms-external-id")).getByText(message),
    ).toBeInTheDocument();
    expect(
      within(fieldWrapper("property-internal-code")).queryByText(message),
    ).not.toBeInTheDocument();
  });

  it("falls back to the generic error banner for an unmatched 409", () => {
    useCreatePropertyMock.mockReturnValue(
      mutationState({
        isError: true,
        error: new ApiError({
          code: "CONFLICT",
          message: "something else conflicted",
          status: 409,
        }),
      }),
    );
    renderForm();

    expect(
      screen.getByText(esProperties.createForm.genericError),
    ).toBeInTheDocument();
  });
});

describe("CreatePropertyForm — double-submit prevention (R1.6)", () => {
  it("disables the submit control and shows pending copy while in flight", () => {
    useCreatePropertyMock.mockReturnValue(
      mutationState({ isPending: true }),
    );
    renderForm();

    const button = screen.getByRole("button", {
      name: esProperties.createForm.submitting,
    });
    expect(button).toBeDisabled();
  });

  it("does not call mutate again from a submit event while already pending", () => {
    const mutate = vi.fn();
    useCreatePropertyMock.mockReturnValue(
      mutationState({ mutate, isPending: true }),
    );
    const { container } = renderForm();

    fireEvent.submit(container.querySelector("form")!);

    expect(mutate).not.toHaveBeenCalled();
  });
});
