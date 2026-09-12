import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import esDashboard from "@/locales/es/dashboard.json";
import esProperties from "@/locales/es/properties.json";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertyDetailDto } from "../../data";
import { MAX_NOTES } from "../../lib/field-limits";

/**
 * Section 6 of `properties-create-web`: the accessibility and keyboard contract
 * of the two property forms (tasks 6.1 and 6.2, R4.2 and R4.3).
 *
 * It lives in one file rather than split across `create-property-form.test.tsx`
 * and `edit-property-form.test.tsx` because every claim below is made about
 * *both* forms and is really a claim about the fieldset they share: a check that
 * only ran against one of them would go green while the other rotted. The two
 * behaviour suites stay where they are; this one only asks whether the result is
 * operable.
 *
 * What jsdom can and cannot answer is the line this file is careful about. It
 * performs no layout, so every assertion here is about the DOM the browser would
 * be handed — roles, names, `aria-*` wiring, element order, `tabindex`, the
 * classes that decide focus and target size. The rendered pixels (44×44 for
 * real, no clipping at 360px) are measured in Chromium by
 * `property-forms-layout.browser.test.tsx`, task 6.3's guard; asserting a class
 * here and a pixel there is the same two-guard split `shell-topbar-overflow-360`
 * established, and neither half alone is the proof.
 */

const pushMock = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const useCreatePropertyMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-create-property", () => ({
  useCreateProperty: useCreatePropertyMock,
}));

const usePropertyMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-property", () => ({
  useProperty: usePropertyMock,
}));

const useUpdatePropertyMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-update-property", () => ({
  useUpdateProperty: useUpdatePropertyMock,
}));

import { CreatePropertyForm } from "./create-property-form";
import { EditPropertyForm } from "./edit-property-form";

const PROPERTY_ID = "property-1";

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

function mutationState() {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
  };
}

beforeEach(() => {
  pushMock.mockReset();
  useCreatePropertyMock.mockReset();
  useCreatePropertyMock.mockReturnValue(mutationState());
  usePropertyMock.mockReset();
  usePropertyMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: DETAIL,
    refetch: vi.fn(),
  });
  useUpdatePropertyMock.mockReset();
  useUpdatePropertyMock.mockReturnValue(mutationState());
});

function renderCreate() {
  return render(
    <I18nProvider locale="es">
      <CreatePropertyForm />
    </I18nProvider>,
  );
}

function renderEdit() {
  return render(
    <I18nProvider locale="es">
      <EditPropertyForm propertyId={PROPERTY_ID} onCancel={vi.fn()} />
    </I18nProvider>,
  );
}

/**
 * The two forms, rendered the way their hosts render them: the create form bare
 * (its `Sheet` supplies no props), the edit form with `onCancel`, which is what
 * makes its Cancel button exist at all (`property-detail-view.tsx` passes it).
 */
const FORMS = [
  ["CreatePropertyForm", renderCreate],
  ["EditPropertyForm", renderEdit],
] as const;

/** Every field control the shared fieldset renders, in the order it renders them. */
const FIELDSET_IDS = [
  "property-name",
  "property-internal-code",
  "property-pms-external-id",
  "property-address-line1",
  "property-address-line2",
  "property-city",
  "property-province",
  "property-postal-code",
  "property-country",
  "property-timezone",
  "property-max-guests",
  "property-bedrooms",
  "property-bathrooms",
  "property-default-check-in-time",
  "property-default-check-out-time",
  "property-wifi-name",
  "property-wifi-password",
  "property-access-notes",
  "property-cleaning-notes",
  "property-emergency-notes",
] as const;

const FIELD_SELECTOR = "input, textarea, select";
const FOCUSABLE_SELECTOR =
  "input, textarea, select, button, a[href], [tabindex]";

function fields(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FIELD_SELECTOR));
}

function focusables(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

function classTokens(element: Element): string[] {
  return (element.getAttribute("class") ?? "").split(/\s+/).filter(Boolean);
}

// ---------------------------------------------------------------------------
// 6.1 — labels, required markers, error association, axe
// ---------------------------------------------------------------------------

describe.each(FORMS)("%s — programmatic labelling (R4.2, task 6.1)", (_name, mount) => {
  it("gives every control a `<label for>` with real text", () => {
    // Not `getByLabelText` per known label: that only proves the labels this
    // test knows about are wired. Walking every control instead is what catches
    // a field ADDED later without one.
    const { container } = mount();
    const controls = fields(container);
    expect(controls.length).toBeGreaterThanOrEqual(FIELDSET_IDS.length);

    for (const control of controls) {
      expect(control.id, `a control renders with no id: ${control.outerHTML}`).not.toBe("");
      const label = container.querySelector(`label[for="${control.id}"]`);
      expect(label, `no <label for="${control.id}">`).not.toBeNull();
      expect(label?.textContent?.trim()).not.toBe("");
    }
  });

  it("marks exactly the two required fields, and marks them programmatically", () => {
    // The visible " *" is `aria-hidden`, so `required` is the only thing a
    // screen reader has to go on. R1.2: every other field has a backend
    // default, so requiring it here would be a lie the backend contradicts.
    const { container } = mount();
    const required = fields(container)
      .filter((control) => control.hasAttribute("required"))
      .map((control) => control.id);
    expect(required).toEqual(["property-name", "property-internal-code"]);
  });

  it("has no axe violations as rendered", async () => {
    const { container } = mount();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe.each(FORMS)("%s — validation errors reach the field (R4.2, task 6.1)", (_name, mount) => {
  it("points the invalid control at its own error message with `aria-describedby`", async () => {
    const { container } = mount();
    const name = container.querySelector<HTMLInputElement>("#property-name")!;
    // Emptying `name` is the one client-side failure both forms share: the
    // create form starts blank, the edit form starts seeded, so clearing it
    // exercises the same `validatePropertyFields` path from either side.
    fireEvent.change(name, { target: { value: "" } });
    fireEvent.submit(container.querySelector("form")!);

    expect(name).toHaveAttribute("aria-invalid", "true");
    const describedBy = name.getAttribute("aria-describedby");
    expect(describedBy, "the invalid field describes nothing").not.toBeNull();

    const error = document.getElementById("property-name-error");
    expect(error, "no error paragraph with the described id").not.toBeNull();
    expect(describedBy?.split(/\s+/)).toContain("property-name-error");
    expect(error?.textContent).toBe(esProperties.createForm.errors.required);
    // `role="alert"` announces the message when it appears; `aria-describedby`
    // is what makes it readable again when focus later lands on the field.
    expect(error).toHaveAttribute("role", "alert");
  });

  it("leaves the valid controls neither invalid nor described by an error", () => {
    const { container } = mount();
    fireEvent.change(container.querySelector("#property-name")!, {
      target: { value: "" },
    });
    fireEvent.submit(container.querySelector("form")!);

    const city = container.querySelector<HTMLInputElement>("#property-city")!;
    expect(city).not.toHaveAttribute("aria-invalid");
    expect(city.getAttribute("aria-describedby")).toBeNull();
  });

  it("keeps the static hints described even while a field is invalid", () => {
    // `access_notes` carries the D14 guidance hint. An error must be ADDED to
    // its `aria-describedby`, not swapped in for the hint.
    const { container } = mount();
    const notes = container.querySelector<HTMLTextAreaElement>(
      "#property-access-notes",
    )!;
    expect(notes.getAttribute("aria-describedby")).toBe(
      "property-access-notes-hint",
    );
    expect(
      document.getElementById("property-access-notes-hint"),
    ).not.toBeNull();

    // One character past `MAX_NOTES` (5000), the bound `validatePropertyFields`
    // enforces. `maxLength` stops a real keystroke; it does not stop a paste
    // programmatically set here, which is exactly the path being exercised.
    fireEvent.change(notes, { target: { value: "x".repeat(MAX_NOTES + 1) } });
    fireEvent.submit(container.querySelector("form")!);
    expect(notes.getAttribute("aria-describedby")?.split(/\s+/)).toEqual([
      "property-access-notes-hint",
      "property-access-notes-error",
    ]);
  });

  it("has no axe violations with errors on screen", async () => {
    const { container } = mount();
    fireEvent.change(container.querySelector("#property-name")!, {
      target: { value: "" },
    });
    fireEvent.submit(container.querySelector("form")!);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 6.1 / 6.2 — focus order, focus visibility, keyboard reach
// ---------------------------------------------------------------------------

describe.each(FORMS)("%s — focus order follows visual order (R4.3)", (_name, mount) => {
  it("puts no element in front of or behind the natural order with `tabindex`", () => {
    // With every `tabindex` either absent or 0, the sequential focus order IS
    // the DOM order — which is the only reason the order check below means
    // anything. A single `tabindex="3"` would silently decouple the two.
    const { container } = mount();
    for (const element of focusables(container)) {
      const tabIndex = element.getAttribute("tabindex");
      expect(
        tabIndex === null || tabIndex === "0",
        `${element.id || element.tagName} carries tabindex="${tabIndex}"`,
      ).toBe(true);
    }
  });

  it("renders the fields in DOM order, and nothing re-orders them visually", () => {
    /*
     * Two halves of one claim, and the second is the one a class-only guard
     * would miss: DOM order is the focus order (above), so visual order matches
     * it only as long as no CSS moves a box. Tailwind can do that with
     * `order-*` or a `*-reverse` flex/grid direction, so the subtree is checked
     * for both rather than assumed free of them.
     */
    const { container } = mount();
    const rendered = fields(container)
      .map((control) => control.id)
      .filter((id) => (FIELDSET_IDS as readonly string[]).includes(id));
    expect(rendered).toEqual([...FIELDSET_IDS]);

    for (const element of container.querySelectorAll("*")) {
      for (const token of classTokens(element)) {
        expect(
          /^(?:.*:)?order-/.test(token) || /-reverse$/.test(token),
          `\`${token}\` on <${element.tagName.toLowerCase()}> re-orders the visual sequence away from the DOM order`,
        ).toBe(false);
      }
      expect(element.getAttribute("style") ?? "").not.toMatch(/order\s*:/);
    }
  });

  it("suppresses no `:focus-visible` without a replacement", () => {
    // `steering/frontend.md`: «no se suprime `:focus-visible` sin una
    // sustitución equivalente». `Button` does exactly that — `outline-none`
    // paired with `focus-visible:ring-2` — and it is the pattern any control
    // here has to follow if it removes the UA ring at all.
    const { container } = mount();
    for (const element of focusables(container)) {
      const tokens = classTokens(element);
      const suppresses = tokens.some((token) =>
        /^(?:focus(?:-visible)?:)?outline-none$/.test(token),
      );
      if (!suppresses) {
        continue;
      }
      expect(
        tokens.some((token) => token.startsWith("focus-visible:ring")),
        `${element.id || element.tagName} removes the focus outline without a focus-visible replacement`,
      ).toBe(true);
    }
  });
});

describe.each(FORMS)("%s — keyboard operability (R4.3, task 6.2)", (_name, mount) => {
  it("keeps every control in the tab sequence and focusable", () => {
    const { container } = mount();
    const controls = focusables(container);
    expect(controls.length).toBeGreaterThan(FIELDSET_IDS.length);

    for (const element of controls) {
      expect(element).not.toHaveAttribute("tabindex", "-1");
      expect(element).not.toHaveAttribute("aria-hidden", "true");
      expect(element.closest("[aria-hidden='true']")).toBeNull();
      element.focus();
      expect(
        document.activeElement,
        `${element.id || element.tagName} cannot take focus`,
      ).toBe(element);
    }
  });

  it("exposes its actions as real `<button>`s, which Enter and Space activate", () => {
    /*
     * jsdom does not implement the UA's activation behaviour, so pressing Enter
     * on a `<button>` here fires no click and a keyboard test would be
     * measuring the harness, not the app. What IS decidable in jsdom is the
     * thing the browser's behaviour depends on: that these are native
     * `<button>` elements with a real `type` — not `<div role="button">`, which
     * looks identical to `getByRole` and responds to neither key. The rendered
     * activation is exercised for real in the browser project.
     */
    const { container } = mount();
    for (const button of container.querySelectorAll("button")) {
      expect(button.tagName).toBe("BUTTON");
      expect(["submit", "button"]).toContain(button.getAttribute("type"));
    }
    // And the submit control really is a submit control, so Enter from inside
    // any text field submits the form the way a keyboard user expects.
    const submits = Array.from(container.querySelectorAll("button")).filter(
      (button) => button.getAttribute("type") === "submit",
    );
    expect(submits).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 6.1 / 6.2 — interaction target size (44×44)
// ---------------------------------------------------------------------------

describe.each(FORMS)("%s — 44×44 interaction targets", (_name, mount) => {
  it("puts `tap-target` on every field control and every button", () => {
    /*
     * The class, not the pixels — jsdom computes no layout, and a test that
     * read `getBoundingClientRect()` here would report 0×0 for everything and
     * pass forever. `property-forms-layout.browser.test.tsx` measures the
     * rendered boxes in Chromium; this pins the intent so a refactor that drops
     * the class fails in the fast suite too.
     *
     * Why it is needed at all: `Button`'s default size is `h-10` (40px) and the
     * fieldset's inputs come out ~36px from `px-3 py-2 text-sm` — both under the
     * 44px floor of `steering/frontend.md`.
     */
    const { container } = mount();
    for (const control of fields(container)) {
      if (control.getAttribute("type") === "checkbox") {
        // The documented exception (`edit-property-form.tsx`): a native
        // checkbox glyph is not resized to 44px; its `<label for>` — which is
        // just as clickable — carries the floor instead.
        const label = container.querySelector(`label[for="${control.id}"]`);
        expect(classTokens(label!)).toContain("tap-target");
        continue;
      }
      expect(
        classTokens(control),
        `${control.id} is under the 44px floor`,
      ).toContain("tap-target");
    }

    for (const button of container.querySelectorAll("button")) {
      expect(
        classTokens(button),
        `«${button.textContent}» is under the 44px floor`,
      ).toContain("tap-target");
    }
  });
});

// ---------------------------------------------------------------------------
// Form-specific control inventory
// ---------------------------------------------------------------------------

describe("the two forms render the controls their hosts rely on", () => {
  it("CreatePropertyForm offers one submit and no cancel", () => {
    const { container } = renderCreate();
    const buttons = Array.from(container.querySelectorAll("button"));
    expect(buttons.map((button) => button.textContent)).toEqual([
      esProperties.createForm.submit,
    ]);
  });

  it("EditPropertyForm offers submit, cancel and the clear-password checkbox", () => {
    const { container } = renderEdit();
    expect(
      Array.from(container.querySelectorAll("button")).map(
        (button) => button.textContent,
      ),
    ).toEqual([esDashboard.detail.edit.submit, esDashboard.detail.edit.cancel]);
    expect(
      screen.getByLabelText(esProperties.editForm.clearWifiPassword),
    ).toHaveAttribute("type", "checkbox");
  });
});
