import { fireEvent } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { getA11yViolations, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esDashboard from "@/locales/es/dashboard.json";

import type { PropertyDetail } from "../../data";

const usePropertyDetail = vi.hoisted(() => vi.fn());
const usePropertyTimeline = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-dashboard-data", () => ({
  usePropertyDetail,
  usePropertyTimeline,
}));

// Same convention `properties-view.test.tsx` established for the create
// affordance: the permission is mocked rather than driven through a real
// `AuthProvider`, and the hosted form is stubbed so opening the `Sheet` never
// reaches its own `useProperty`/`useUpdateProperty` (it has its own test file,
// `features/properties/components/form/edit-property-form.test.tsx`).
const useHasPermissionMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("@/lib/auth", () => ({
  useHasPermission: useHasPermissionMock,
}));

// `PropertyDetailView` reads the property's own `status` (for the retire
// gate, R2.6/D9) through the same `useProperty` `EditPropertyForm` uses, and
// drives the retire confirmation through `useUpdateProperty` — both mocked
// here so this suite never reaches react-query/the data layer, same
// convention as `EditPropertyForm` being stubbed below.
const usePropertyMock = vi.hoisted(() => vi.fn());
const useUpdatePropertyMock = vi.hoisted(() => vi.fn());
const updatePropertyMutate = vi.hoisted(() => vi.fn());
vi.mock("@/features/properties", () => ({
  // The stub owns its own local state (`useState`), same as the real
  // `EditPropertyForm` — its own field values live in a component instance
  // entirely separate from `PropertyDetailView`'s retire state (R2.6, design
  // D9). The extra labelled field lets a test dirty it without saving, so
  // `property-detail-view.test.tsx` can prove the retire `AlertDialog` never
  // reads from — or resets — it (sdd-qa finding 2). The identifying text sits
  // in its own `<span>` so it keeps matching `getByText("edit-property-form-
  // stub:<id>")` exactly, unaffected by the field markup alongside it.
  EditPropertyForm: ({ propertyId }: { propertyId: string }) => {
    const [value, setValue] = useState("");
    return (
      <div>
        <span>edit-property-form-stub:{propertyId}</span>
        <label htmlFor="edit-form-stub-field">edit-form-stub-field</label>
        <input
          id="edit-form-stub-field"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>
    );
  },
  useProperty: usePropertyMock,
  useUpdateProperty: useUpdatePropertyMock,
}));

import { PropertyDetailView } from "./property-detail-view";

const detail: PropertyDetail = {
  propertyId: "redes11",
  propertyCode: "REDES11",
  operationalState: "AWAITING_CLEANING",
  currentOrNextReservation: null,
  guest: null,
  access: null,
  cleaningStatus: null,
  lastCleaningPhotos: [],
  openIncidents: [],
  financial: null,
  notes: null,
  pendingApprovals: [],
};

function renderView(id = "redes11") {
  return render(
    <I18nProvider locale="es">
      <PropertyDetailView propertyId={id} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  usePropertyDetail.mockReset();
  usePropertyTimeline.mockReset();
  useHasPermissionMock.mockReset();
  useHasPermissionMock.mockReturnValue(true);
  usePropertyTimeline.mockReturnValue({
    isPending: false,
    isError: false,
    data: { data: [], total: 0, page: 1, per_page: 0, total_pages: 0 },
  });
  usePropertyMock.mockReset();
  usePropertyMock.mockReturnValue({
    isPending: false,
    isError: false,
    data: { status: "ACTIVE" },
  });
  useUpdatePropertyMock.mockReset();
  updatePropertyMutate.mockReset();
  useUpdatePropertyMock.mockReturnValue({
    mutate: updatePropertyMutate,
    isPending: false,
    isError: false,
    error: null,
  });
});

describe("PropertyDetailView (R2)", () => {
  it("shows the loading state while pending", () => {
    usePropertyDetail.mockReturnValue({ isPending: true, isError: false });
    renderView();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders a localized not-found for a §23 404", () => {
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "nope", status: 404 }),
    });
    renderView("unknown");
    expect(screen.getByText("Propiedad no encontrada")).toBeInTheDocument();
  });

  it("renders the error convention with retry for a non-404 failure", () => {
    const refetch = vi.fn();
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
      refetch,
    });
    renderView();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("renders the detail sections and timeline on success", () => {
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: false,
      data: detail,
    });
    renderView();
    expect(
      screen.getByRole("heading", { name: "REDES11", level: 1 }),
    ).toBeInTheDocument();
    // Timeline section heading is present (composed view).
    expect(
      screen.getByRole("heading", { name: "Cronología" }),
    ).toBeInTheDocument();
  });
});

describe("PropertyDetailView — edit affordance (R2.1, design D3/D13)", () => {
  function ok() {
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: false,
      data: detail,
    });
  }

  it("offers the edit action with MANAGE_PROPERTIES", () => {
    ok();
    renderView();
    expect(
      screen.getByRole("button", { name: esDashboard.detail.edit.button }),
    ).toBeInTheDocument();
    expect(useHasPermissionMock).toHaveBeenCalledWith("MANAGE_PROPERTIES");
  });

  it("hides the edit action without the permission", () => {
    useHasPermissionMock.mockReturnValue(false);
    ok();
    renderView();
    expect(
      screen.queryByRole("button", { name: esDashboard.detail.edit.button }),
    ).not.toBeInTheDocument();
  });

  it("opens the Sheet hosting EditPropertyForm and closes it again", () => {
    ok();
    renderView();

    expect(
      screen.queryByText("edit-property-form-stub:redes11"),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.edit.button }),
    );
    // The sheet's own title comes from `dashboard` (design D13) and the form is
    // handed the id of the property this view is showing.
    expect(
      screen.getByRole("heading", { name: esDashboard.detail.edit.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("edit-property-form-stub:redes11"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.edit.close }),
    );
    expect(
      screen.queryByText("edit-property-form-stub:redes11"),
    ).not.toBeInTheDocument();
  });
});

describe("PropertyDetailView — retire affordance (R2.6, design D9)", () => {
  function ok() {
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: false,
      data: detail,
    });
  }

  it("offers the retire action with MANAGE_PROPERTIES and an active property", () => {
    ok();
    renderView();
    expect(
      screen.getByRole("button", { name: esDashboard.detail.retire.button }),
    ).toBeInTheDocument();
  });

  it("hides the retire action without the permission", () => {
    useHasPermissionMock.mockReturnValue(false);
    ok();
    renderView();
    expect(
      screen.queryByRole("button", { name: esDashboard.detail.retire.button }),
    ).not.toBeInTheDocument();
  });

  it("hides the retire action once the property is already INACTIVE", () => {
    usePropertyMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { status: "INACTIVE" },
    });
    ok();
    renderView();
    expect(
      screen.queryByRole("button", { name: esDashboard.detail.retire.button }),
    ).not.toBeInTheDocument();
  });

  it("hides the retire action while the property's own status has not loaded yet", () => {
    usePropertyMock.mockReturnValue({
      isPending: true,
      isError: false,
      data: undefined,
    });
    ok();
    renderView();
    expect(
      screen.queryByRole("button", { name: esDashboard.detail.retire.button }),
    ).not.toBeInTheDocument();
  });

  it("opens the confirmation AlertDialog and confirming calls the mutation with exactly {status: INACTIVE}", () => {
    ok();
    renderView();

    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.retire.button }),
    );
    expect(
      screen.getByRole("heading", { name: esDashboard.detail.retire.title }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.retire.confirm }),
    );

    expect(updatePropertyMutate).toHaveBeenCalledTimes(1);
    expect(updatePropertyMutate).toHaveBeenCalledWith(
      { id: "redes11", input: { status: "INACTIVE" } },
      expect.any(Object),
    );
  });

  it("cancelling the dialog makes no request", () => {
    ok();
    renderView();

    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.retire.button }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.retire.cancel }),
    );

    expect(updatePropertyMutate).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("heading", { name: esDashboard.detail.retire.title }),
    ).not.toBeInTheDocument();
  });

  it("renders the generic error and keeps the dialog open when the mutation fails", () => {
    useUpdatePropertyMock.mockReturnValue({
      mutate: updatePropertyMutate,
      isPending: false,
      isError: true,
      error: new Error("boom"),
    });
    ok();
    renderView();

    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.retire.button }),
    );

    expect(screen.getByRole("alert").textContent).toBe(
      esDashboard.detail.retire.genericError,
    );
    expect(
      screen.getByRole("heading", { name: esDashboard.detail.retire.title }),
    ).toBeInTheDocument();
  });
});

/**
 * R2.6/design D9: the edit `Sheet` and the retire `AlertDialog` are backed by
 * two wholly separate component instances (`EditPropertyForm`'s own local
 * state vs. `PropertyDetailView`'s own `useUpdateProperty()` call for
 * retire) — confirmed correct by earlier section reviews, but never
 * exercised together in one test before sdd-qa finding 2.
 *
 * **What this proves, precisely.** It is a *state-independence* guard between
 * two mutation call sites, driven by direct DOM events against mocked hooks:
 * a retire body can never pick up whatever `EditPropertyForm` is holding,
 * because the two never share an instance. It is NOT a claim that a user can
 * operate both overlays at once — they cannot. The edit `Sheet` is a modal
 * Radix dialog (`components/ui/sheet.tsx` → `SheetPrimitive.Root` with a
 * `Portal` + full-screen `Overlay`), so in a real browser the Retire trigger
 * behind it is neither clickable (the overlay takes the pointer events) nor
 * keyboard-reachable (outside the focus trap, `aria-hidden` in the
 * accessibility tree); the two are mutually exclusive by construction and the
 * user closes the Sheet before reaching Retire. This test can drive them
 * together only because `fireEvent` dispatches events directly on the node,
 * bypassing the hit-testing, `pointer-events` and `aria-hidden` enforcement
 * that a browser and a screen reader apply — which is exactly what makes it a
 * usable probe for the coupling question, and exactly why it says nothing
 * about simultaneous interactivity. See design D9.
 */
describe("PropertyDetailView — the edit Sheet and retire AlertDialog stay independent (R2.6, design D9)", () => {
  it("keeps the edit form's dirtied-but-unsaved field untouched by the retire mutation, and vice versa", () => {
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: false,
      data: detail,
    });
    renderView();

    // Dirty the edit form's own field without ever saving it.
    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.edit.button }),
    );
    const editField = screen.getByLabelText("edit-form-stub-field");
    fireEvent.change(editField, { target: { value: "unsaved-change" } });
    expect(editField).toHaveValue("unsaved-change");

    // Open and confirm the retire AlertDialog with the edit Sheet left
    // mounted and open — the hostile arrangement for the coupling question,
    // not a reachable one for a user (see this describe's note).
    // Radix's modal `Sheet` marks the rest of the page `aria-hidden` while it
    // is open, so the retire trigger (outside the Sheet's own portal) needs
    // `{ hidden: true }` here to be queryable by role at all. That flag is
    // the tell: in a real browser this trigger is hidden from assistive tech
    // and sits behind the Sheet's overlay, so `fireEvent` reaching it is a
    // deliberate bypass of hit-testing — it drives the two mutation call
    // sites together to prove they share no state, and asserts nothing about
    // whether a user could do this.
    fireEvent.click(
      screen.getByRole("button", {
        name: esDashboard.detail.retire.button,
        hidden: true,
      }),
    );
    // Confirm is queried without `hidden: true`: the AlertDialog being open
    // now hides everything else (main page and edit Sheet alike), including
    // the retire trigger that shares this exact same label, so only the
    // dialog's own button is left in the accessible tree.
    fireEvent.click(
      screen.getByRole("button", { name: esDashboard.detail.retire.confirm }),
    );

    // The retire mutation carries exactly `{ status: "INACTIVE" }` — nothing
    // merged in from the edit form's pending, unsaved value.
    expect(updatePropertyMutate).toHaveBeenCalledTimes(1);
    expect(updatePropertyMutate).toHaveBeenCalledWith(
      { id: "redes11", input: { status: "INACTIVE" } },
      expect.any(Object),
    );

    // ...and the edit form's own unsaved value is still exactly what was
    // typed: neither mutation call leaked state into the other.
    expect(editField).toHaveValue("unsaved-change");
  });
});

/**
 * Section 6 (task 6.2, R4.3) for the two overlays this view owns.
 *
 * `property-forms-a11y.test.tsx` covers the two forms; this covers what hosts
 * them — the edit `Sheet` and the retire `AlertDialog`, which task 6.2 names
 * explicitly. The rendered boxes (44×44 for real, no clipping at 360px) are
 * measured in Chromium by
 * `features/properties/components/form/property-forms-layout.browser.test.tsx`;
 * everything here is about the DOM jsdom can answer for.
 */
describe("PropertyDetailView — the overlays' keyboard contract (R4.3, task 6.2)", () => {
  function ok() {
    usePropertyDetail.mockReturnValue({
      isPending: false,
      isError: false,
      data: detail,
    });
  }

  /** Focuses the named trigger the way a keyboard user reaches it, then activates it. */
  function openFrom(name: string): HTMLElement {
    ok();
    renderView();
    const trigger = screen.getByRole("button", { name });
    // Radix records `document.activeElement` at open time; opening from an
    // unfocused trigger would leave the assertions below measuring nothing.
    trigger.focus();
    fireEvent.click(trigger);
    return trigger;
  }

  it("closes the edit Sheet on Escape and returns focus to the Edit button", async () => {
    const trigger = openFrom(esDashboard.detail.edit.button);
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    // The half a "did it close?" check misses: without the `onCloseAutoFocus`
    // in `property-detail-view.tsx` focus lands on `<body>` and a keyboard user
    // restarts from the top of the document.
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("closes the retire AlertDialog on Escape, makes no request, and returns focus", async () => {
    const trigger = openFrom(esDashboard.detail.retire.button);
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    // Escape is a dismissal, never a confirmation of a destructive action.
    expect(updatePropertyMutate).not.toHaveBeenCalled();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("keeps both retire buttons in the tab sequence and focusable", async () => {
    openFrom(esDashboard.detail.retire.button);
    const dialog = await screen.findByRole("alertdialog");

    const buttons = Array.from(dialog.querySelectorAll("button"));
    expect(buttons.map((button) => button.textContent)).toEqual([
      esDashboard.detail.retire.cancel,
      esDashboard.detail.retire.confirm,
    ]);

    for (const button of buttons) {
      expect(button).not.toHaveAttribute("tabindex", "-1");
      expect(button).not.toBeDisabled();
      // Native `<button>` with a real `type`, not a `<div role="button">`:
      // that is what makes Enter and Space activate it in a real browser, which
      // jsdom does not implement and so cannot be pressed for here.
      expect(button.tagName).toBe("BUTTON");
      expect(button.getAttribute("type")).toBe("button");
      button.focus();
      expect(document.activeElement).toBe(button);
    }
  });

  it("gives every trigger and both dialog buttons a 44×44 target", async () => {
    /*
     * The class, not the pixels — jsdom computes no layout. The two dialog
     * buttons are the regression guard for the shared-primitive fix in
     * `components/ui/alert-dialog.tsx`: `AlertDialogAction`/`AlertDialogCancel`
     * used to destructure `className` and never forward it to the wrapped
     * `Button`, so this exact assertion failed while the call site looked
     * correct. Measured for real in `property-forms-layout.browser.test.tsx`.
     */
    expect(openFrom(esDashboard.detail.edit.button)).toHaveClass("tap-target");
    fireEvent.keyDown(await screen.findByRole("dialog"), { key: "Escape" });

    const retire = screen.getByRole("button", {
      name: esDashboard.detail.retire.button,
    });
    expect(retire).toHaveClass("tap-target");

    fireEvent.click(retire);
    const dialog = await screen.findByRole("alertdialog");
    for (const button of dialog.querySelectorAll("button")) {
      expect(
        button.getAttribute("class")?.split(/\s+/),
        `«${button.textContent}» is under the 44px floor`,
      ).toContain("tap-target");
    }
  });

  it("has no axe violations with the retire AlertDialog open", async () => {
    openFrom(esDashboard.detail.retire.button);
    const dialog = await screen.findByRole("alertdialog");
    // Scoped to the dialog: a component test renders no landmarks, so a
    // document-wide scan reports `region` against the portal rather than
    // against this surface (same reason `properties-view.test.tsx` records).
    expect(await getA11yViolations(dialog)).toEqual([]);
  });
});
