import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import esProperties from "@/locales/es/properties.json";
import { render, screen } from "@/test/render";

import { PropertyFieldset, type PropertyFormFields } from "./property-fieldset";

const VALUES: PropertyFormFields = {
  name: "",
  internal_code: "",
  pms_external_id: "",
  address_line1: "",
  address_line2: "",
  city: "",
  province: "",
  postal_code: "",
  country: "ES",
  timezone: "Europe/Madrid",
  max_guests: 2,
  bedrooms: 1,
  bathrooms: 1,
  default_check_in_time: "15:00",
  default_check_out_time: "11:00",
  wifi_name: "",
  wifi_password: "",
  access_notes: "",
  cleaning_notes: "",
  emergency_notes: "",
};

function renderFieldset(fieldErrors: Record<string, string> = {}) {
  return render(
    <I18nProvider locale="es">
      <PropertyFieldset
        values={VALUES}
        onChange={vi.fn()}
        fieldErrors={fieldErrors}
      />
    </I18nProvider>,
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * `name`/`internal_code`/`timezone` append a visible, `aria-hidden` " *"
 * required marker (UI-UX finding 1; `timezone` added for sdd-qa finding 1)
 * that is not part of the translated label string itself — matched here as
 * an optional suffix, anchored, so a short label (e.g. "Nombre") cannot
 * ambiguously match a longer, unrelated one that merely contains it as a
 * substring (e.g. "Nombre del WiFi").
 */
function labelMatcher(label: string): RegExp {
  return new RegExp(`^${escapeRegExp(label)}( \\*)?$`);
}

describe("PropertyFieldset — the ~15-field list (R1.2, R4.2)", () => {
  it("gives every field a programmatically associated label", () => {
    renderFieldset();
    for (const label of Object.values(esProperties.createForm.fields)) {
      expect(screen.getByLabelText(labelMatcher(label))).toBeInTheDocument();
    }
  });

  it("marks only name, internal_code and timezone as required", () => {
    renderFieldset();
    expect(
      screen.getByLabelText(labelMatcher(esProperties.createForm.fields.name)),
    ).toBeRequired();
    expect(
      screen.getByLabelText(
        labelMatcher(esProperties.createForm.fields.internalCode),
      ),
    ).toBeRequired();
    expect(
      screen.getByLabelText(
        labelMatcher(esProperties.createForm.fields.timezone),
      ),
    ).toBeRequired();
    expect(
      screen.getByLabelText(esProperties.createForm.fields.city),
    ).not.toBeRequired();
  });

  it("visibly marks name, internal_code and timezone as required, unlike the optional fields (UI-UX finding 1; timezone added for sdd-qa finding 1)", () => {
    const { container } = renderFieldset();
    const nameLabel = container.querySelector('label[for="property-name"]')!;
    const internalCodeLabel = container.querySelector(
      'label[for="property-internal-code"]',
    )!;
    const timezoneLabel = container.querySelector(
      'label[for="property-timezone"]',
    )!;
    const cityLabel = container.querySelector('label[for="property-city"]')!;

    expect(nameLabel.textContent).toContain("*");
    expect(internalCodeLabel.textContent).toContain("*");
    expect(timezoneLabel.textContent).toContain("*");
    expect(cityLabel.textContent).not.toContain("*");

    // The asterisk is hidden from assistive tech (`required` already conveys
    // it there) — it must not be announced as literal "asterisk" text.
    const nameMarker = nameLabel.querySelector("span");
    expect(nameMarker).toHaveAttribute("aria-hidden", "true");
    const timezoneMarker = timezoneLabel.querySelector("span");
    expect(timezoneMarker).toHaveAttribute("aria-hidden", "true");
  });

  it("never renders a pms_provider or status control (R1.2)", () => {
    const { container } = renderFieldset();
    expect(container.querySelector("#property-pms-provider")).toBeNull();
    expect(container.querySelector("#property-status")).toBeNull();
  });

  it("shows the access_notes inline guidance (design D14, R3.1)", () => {
    renderFieldset();
    expect(
      screen.getByText(esProperties.createForm.accessNotesHint),
    ).toBeInTheDocument();
  });

  it("starts wifi_password blank and masked (R3.2)", () => {
    renderFieldset();
    const input = screen.getByLabelText(
      esProperties.createForm.fields.wifiPassword,
    ) as HTMLInputElement;
    expect(input.value).toBe("");
    expect(input).toHaveAttribute("type", "password");
  });

  it("shows a field error message next to its field", () => {
    renderFieldset({ internal_code: "ya existe" });
    expect(screen.getByText("ya existe")).toBeInTheDocument();
  });
});
