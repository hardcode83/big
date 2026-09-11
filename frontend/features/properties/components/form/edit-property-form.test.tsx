import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esDashboard from "@/locales/es/dashboard.json";
import esProperties from "@/locales/es/properties.json";
import { fireEvent, render, screen, within } from "@/test/render";

import type { PropertyDetailDto } from "../../data";

const usePropertyMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-property", () => ({
  useProperty: usePropertyMock,
}));

const useUpdatePropertyMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-update-property", () => ({
  useUpdateProperty: useUpdatePropertyMock,
}));

import { EditPropertyForm } from "./edit-property-form";

const PROPERTY_ID = "property-1";

/**
 * A fully populated property: every nullable column non-empty except
 * `emergencyNotes`, which is `null` on purpose — it is the "already empty"
 * case R2.4 says must never travel as `null` for merely being left alone.
 *
 * There is no `wifiPassword` key here, and there cannot be: `PropertyDetailDto`
 * has no such field because `PropertyResponse` never returns one (R2.5). Only
 * `hasWifiPassword` says a password exists at all.
 */
const DETAIL: PropertyDetailDto = {
  id: PROPERTY_ID,
  name: "Redes 11",
  internalCode: "REDES11",
  pmsProvider: "BEDS24",
  pmsExternalId: "ext-9999",
  addressLine1: "Calle Redes 11",
  addressLine2: "3ºB",
  city: "Madrid",
  province: "ZZ-PROVINCE",
  postalCode: "28051",
  country: "ES",
  timezone: "Europe/Madrid",
  maxGuests: 4,
  bedrooms: 2,
  bathrooms: 1,
  currentOperationalState: "AWAITING_CLEANING",
  defaultCheckInTime: "15:00:00",
  defaultCheckOutTime: "11:00:00",
  wifiName: "RedesWifi",
  hasWifiPassword: true,
  status: "ACTIVE",
  createdAt: "1999-01-02T03:04:05Z",
  updatedAt: "1999-01-03T03:04:05Z",
  accessNotes: "El portal está a la derecha",
  cleaningNotes: "Sábanas en el armario",
  emergencyNotes: null,
};

function mutationState(
  overrides: Partial<{
    mutate: ReturnType<typeof vi.fn>;
    isPending: boolean;
    isError: boolean;
    isSuccess: boolean;
    error: unknown;
  }> = {},
) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    ...overrides,
  };
}

function queryState(overrides: Record<string, unknown> = {}) {
  return {
    isPending: false,
    isError: false,
    data: DETAIL,
    refetch: vi.fn(),
    ...overrides,
  };
}

function renderForm() {
  return render(
    <I18nProvider locale="es">
      <EditPropertyForm propertyId={PROPERTY_ID} />
    </I18nProvider>,
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Same anchored matcher `create-property-form.test.tsx` uses, same reason. */
function labelMatcher(label: string): RegExp {
  return new RegExp(`^${escapeRegExp(label)}( \\*)?$`);
}

function field(label: string): HTMLInputElement | HTMLTextAreaElement {
  return screen.getByLabelText(labelMatcher(label)) as
    | HTMLInputElement
    | HTMLTextAreaElement;
}

/** `property-fieldset.tsx`'s per-field wrapper — the field/error association. */
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

function submit() {
  fireEvent.click(
    screen.getByRole("button", { name: esDashboard.detail.edit.submit }),
  );
}

/** The single `PATCH` body the one `mutate` call carried. */
function submittedInput(mutate: ReturnType<typeof vi.fn>) {
  expect(mutate).toHaveBeenCalledTimes(1);
  const [variables] = mutate.mock.calls[0];
  expect(variables.id).toBe(PROPERTY_ID);
  return variables.input as Record<string, unknown>;
}

function setUp(mutate = vi.fn()) {
  usePropertyMock.mockReturnValue(queryState());
  useUpdatePropertyMock.mockReturnValue(mutationState({ mutate }));
  renderForm();
  return mutate;
}

beforeEach(() => {
  usePropertyMock.mockReset();
  useUpdatePropertyMock.mockReset();
});

describe("EditPropertyForm — pre-fill from the fetched property (R2.2)", () => {
  it("seeds every field from the detail response", () => {
    setUp();

    expect(field(esProperties.createForm.fields.name)).toHaveValue("Redes 11");
    expect(field(esProperties.createForm.fields.internalCode)).toHaveValue(
      "REDES11",
    );
    expect(field(esProperties.createForm.fields.city)).toHaveValue("Madrid");
    expect(field(esProperties.createForm.fields.maxGuests)).toHaveValue(4);
    expect(field(esProperties.createForm.fields.accessNotes)).toHaveValue(
      "El portal está a la derecha",
    );
    // `"HH:MM:SS"` on the wire, `"HH:MM"` in an `<input type="time">`.
    expect(
      field(esProperties.createForm.fields.defaultCheckInTime),
    ).toHaveValue("15:00");
    // A `null` column pre-fills as empty, not as the string "null".
    expect(field(esProperties.createForm.fields.emergencyNotes)).toHaveValue("");
  });

  it("never pre-fills the WiFi password, even though the property has one (R2.5)", () => {
    setUp();

    expect(field(esProperties.createForm.fields.wifiPassword)).toHaveValue("");
    expect(screen.getByLabelText(esProperties.editForm.clearWifiPassword)).not.toBeChecked();
  });

  it("renders neither the PMS provider nor the status/operational state (R2.3)", () => {
    setUp();

    // `PropertyFormFields` has no key for either, so nothing binds them — this
    // asserts the rendered surface, which is what R2.3 is about.
    expect(screen.queryByDisplayValue("BEDS24")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("ACTIVE")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("AWAITING_CLEANING")).not.toBeInTheDocument();
  });

  it("shows the loading state while the fetch is pending", () => {
    usePropertyMock.mockReturnValue(
      queryState({ isPending: true, data: undefined }),
    );
    useUpdatePropertyMock.mockReturnValue(mutationState());
    renderForm();

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the error convention when the fetch fails", () => {
    const refetch = vi.fn();
    usePropertyMock.mockReturnValue(
      queryState({
        isError: true,
        data: undefined,
        error: new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
        refetch,
      }),
    );
    useUpdatePropertyMock.mockReturnValue(mutationState());
    renderForm();

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

describe("EditPropertyForm — a background refetch does not clobber in-progress edits (R2.2)", () => {
  it("keeps a typed value after `useProperty` returns a new object for the same property", () => {
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(mutationState());
    const { rerender } = renderForm();

    fireEvent.change(field(esProperties.createForm.fields.name), {
      target: { value: "Redes 12" },
    });

    // TanStack Query's background refetch (window focus, another mutation's
    // invalidation): a fresh `data` object, equal in content, for the same
    // `propertyId`. The render-phase seeding guard
    // (`state.propertyId === propertyId`) must treat this as "already seeded",
    // not re-seed from it and wipe the in-progress edit.
    usePropertyMock.mockReturnValue(queryState({ data: { ...DETAIL } }));
    rerender(
      <I18nProvider locale="es">
        <EditPropertyForm propertyId={PROPERTY_ID} />
      </I18nProvider>,
    );

    expect(field(esProperties.createForm.fields.name)).toHaveValue("Redes 12");
  });
});

describe("EditPropertyForm — only changed fields travel (R2.2, design D8)", () => {
  it("sends an empty body when nothing was touched", () => {
    const mutate = setUp();

    submit();

    expect(submittedInput(mutate)).toEqual({});
  });

  it("sends exactly the one field that changed", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.name), {
      target: { value: "Redes 12" },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ name: "Redes 12" });
  });

  it("never sends `status` — retiring is a separate action (R2.3, design D9)", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.city), {
      target: { value: "Sevilla" },
    });
    submit();

    expect(submittedInput(mutate)).not.toHaveProperty("status");
  });

  it("sends a changed number as a number, not as the input's string", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.bedrooms), {
      target: { value: "3" },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ bedrooms: 3 });
  });

  it("re-adds the seconds a `<input type=\"time\">` drops", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.defaultCheckInTime), {
      target: { value: "16:30" },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ defaultCheckInTime: "16:30:00" });
  });
});

describe("EditPropertyForm — explicit clear vs. left alone (R2.4)", () => {
  it("sends `null` for exactly the nullable field the user cleared, and omits the rest", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.city), {
      target: { value: "" },
    });
    submit();

    const input = submittedInput(mutate);
    expect(input).toEqual({ city: null });
    // The other nullable columns were not touched, so they must not be cleared
    // along with it — this is the whole point of D8's diff.
    expect(input).not.toHaveProperty("province");
    expect(input).not.toHaveProperty("addressLine1");
    expect(input).not.toHaveProperty("accessNotes");
  });

  it("omits a nullable field that was already empty and stayed empty", () => {
    const mutate = setUp();

    // `emergencyNotes` arrived as `null` and nobody typed in it.
    submit();

    expect(submittedInput(mutate)).not.toHaveProperty("emergencyNotes");
  });

  it("omits a nullable field that was already empty and only received whitespace", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.emergencyNotes), {
      target: { value: "   " },
    });
    submit();

    // Blank-to-blank is still "untouched": `null` here would clear a column the
    // user never meant to touch.
    expect(submittedInput(mutate)).toEqual({});
  });

  it("clears a nullable field emptied down to whitespace from a real value", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.accessNotes), {
      target: { value: "  " },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ accessNotes: null });
  });

  it("blocks the submit instead of clearing a required field (design D8)", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.name), {
      target: { value: "" },
    });
    submit();

    expect(mutate).not.toHaveBeenCalled();
    expect(
      screen.getByText(esProperties.createForm.errors.required),
    ).toBeInTheDocument();
  });
});

describe("EditPropertyForm — the write-only WiFi password (R2.5, design D8)", () => {
  it("omits `wifiPassword` when the field is blank and the checkbox unchecked", () => {
    const mutate = setUp();

    submit();

    expect(submittedInput(mutate)).not.toHaveProperty("wifiPassword");
  });

  it("sends a typed password as the new value", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.wifiPassword), {
      target: { value: "nueva-clave" },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ wifiPassword: "nueva-clave" });
  });

  it("sends `wifiPassword: null` when 'clear stored password' is checked and the field left blank", () => {
    const mutate = setUp();

    fireEvent.click(
      screen.getByLabelText(esProperties.editForm.clearWifiPassword),
    );
    submit();

    expect(submittedInput(mutate)).toEqual({ wifiPassword: null });
  });

  it("lets a typed password win over an earlier 'clear', never sending both answers", () => {
    const mutate = setUp();

    fireEvent.click(
      screen.getByLabelText(esProperties.editForm.clearWifiPassword),
    );
    fireEvent.change(field(esProperties.createForm.fields.wifiPassword), {
      target: { value: "nueva-clave" },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ wifiPassword: "nueva-clave" });
    expect(
      screen.getByLabelText(esProperties.editForm.clearWifiPassword),
    ).not.toBeChecked();
  });

  it("empties a typed password when 'clear stored password' is checked afterwards", () => {
    const mutate = setUp();

    fireEvent.change(field(esProperties.createForm.fields.wifiPassword), {
      target: { value: "nueva-clave" },
    });
    fireEvent.click(
      screen.getByLabelText(esProperties.editForm.clearWifiPassword),
    );
    submit();

    expect(submittedInput(mutate)).toEqual({ wifiPassword: null });
    expect(field(esProperties.createForm.fields.wifiPassword)).toHaveValue("");
  });
});

describe("EditPropertyForm — 409 conflicts attribute to the right field (R2.7)", () => {
  it("attributes a duplicate internal_code to that field, not to pms_external_id", () => {
    const message = "A property with that internal_code already exists for this tenant";
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(
      mutationState({
        isError: true,
        error: new ApiError({ code: "CONFLICT", message, status: 409 }),
      }),
    );
    renderForm();

    expect(
      within(fieldWrapper("property-internal-code")).getByText(message),
    ).toBeInTheDocument();
    expect(
      within(fieldWrapper("property-pms-external-id")).queryByText(message),
    ).not.toBeInTheDocument();
  });

  it("attributes a duplicate pms_external_id to that field, not to internal_code", () => {
    const message = "Another property of this tenant already claims that pms_external_id";
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(
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

  it("falls back to the generic banner, in the dashboard namespace, for an unmatched failure", () => {
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(
      mutationState({
        isError: true,
        error: new ApiError({
          code: "SERVER_ERROR",
          message: "boom",
          status: 500,
        }),
      }),
    );
    renderForm();

    expect(
      screen.getByText(esDashboard.detail.edit.genericError),
    ).toBeInTheDocument();
  });
});

describe("EditPropertyForm — pending state and double-submit prevention (R2.8)", () => {
  it("disables the submit control and shows pending copy while in flight", () => {
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(mutationState({ isPending: true }));
    renderForm();

    expect(
      screen.getByRole("button", { name: esDashboard.detail.edit.submitting }),
    ).toBeDisabled();
  });

  it("does not call mutate again from a submit event while already pending", () => {
    const mutate = vi.fn();
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(
      mutationState({ mutate, isPending: true }),
    );
    const { container } = renderForm();

    fireEvent.submit(container.querySelector("form")!);

    expect(mutate).not.toHaveBeenCalled();
  });
});

describe("EditPropertyForm — after a successful save", () => {
  it("re-seeds from the server's answer and reports success", () => {
    const saved: PropertyDetailDto = { ...DETAIL, city: null, name: "Redes 12" };
    const mutate = vi.fn((_variables, opts) => {
      opts?.onSuccess?.(saved);
    });
    const onSaved = vi.fn();
    usePropertyMock.mockReturnValue(queryState());
    useUpdatePropertyMock.mockReturnValue(
      mutationState({ mutate, isSuccess: true }),
    );
    render(
      <I18nProvider locale="es">
        <EditPropertyForm propertyId={PROPERTY_ID} onSaved={onSaved} />
      </I18nProvider>,
    );

    fireEvent.change(field(esProperties.createForm.fields.name), {
      target: { value: "Redes 12" },
    });
    fireEvent.change(field(esProperties.createForm.fields.city), {
      target: { value: "" },
    });
    submit();

    expect(submittedInput(mutate)).toEqual({ name: "Redes 12", city: null });
    expect(onSaved).toHaveBeenCalledWith(saved);
    expect(
      screen.getByText(esDashboard.detail.edit.success),
    ).toBeInTheDocument();

    // The saved values are the new baseline: saving again diffs against them,
    // so an untouched second save is a no-op body rather than a replay.
    mutate.mockClear();
    submit();
    expect(submittedInput(mutate)).toEqual({});
  });

  it("renders a cancel control only when the host supplies a dismissal", () => {
    setUp();
    expect(
      screen.queryByRole("button", { name: esDashboard.detail.edit.cancel }),
    ).not.toBeInTheDocument();

    const onCancel = vi.fn();
    render(
      <I18nProvider locale="es">
        <EditPropertyForm propertyId={PROPERTY_ID} onCancel={onCancel} />
      </I18nProvider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.edit.cancel }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
