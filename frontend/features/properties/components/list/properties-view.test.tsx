import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esDashboard from "@/locales/es/dashboard.json";
import esProperties from "@/locales/es/properties.json";
import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
  within,
} from "@/test/render";

const usePropertiesMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../hooks/use-properties")>()),
  useProperties: usePropertiesMock,
}));

const useHasPermissionMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("@/lib/auth", () => ({
  useHasPermission: useHasPermissionMock,
}));

// `CreatePropertyForm` has its own dedicated test file (`create-property-form.test.tsx`).
// Stubbed here so opening the Sheet in these tests never reaches its real
// `useCreateProperty`/`next/navigation` dependencies.
vi.mock("../form/create-property-form", () => ({
  CreatePropertyForm: () => <div>create-property-form-stub</div>,
}));

import { PropertiesView } from "./properties-view";

function renderView() {
  return render(
    <I18nProvider locale="es">
      <PropertiesView />
    </I18nProvider>,
  );
}

/**
 * The view renders BOTH layouts into the DOM — stacked cards for `<sm`, the
 * table from `sm` up — and Tailwind's `hidden`/`sm:block` decides which one is
 * visible. jsdom applies no Tailwind stylesheet, so both are present here and
 * every text query must be scoped to one of them. That is a testing artifact of
 * the responsive pattern, not duplicate content in a browser.
 */
const table = () => screen.getByRole("table");
const cardList = () => screen.getAllByRole("article");

const ROW = {
  id: "property-1",
  name: "Redes 11",
  internalCode: "REDES11",
  pmsProvider: "BEDS24",
  pmsExternalId: "ext-9999",
  addressLine1: "Calle Redes 11",
  addressLine2: "3ºB",
  city: "Madrid",
  // `province` MUST differ from `city` here. In real seeded data both are
  // "Madrid", which makes a leaked `province` cell structurally undetectable by
  // a text denylist: it cannot be told apart from the `city` that is rendered
  // legitimately. Raised by the QA panel on sections 4–6.
  province: "ZZ-PROVINCE",
  postalCode: "28051",
  // Same reason for `country`: the real value is "ES", a two-letter substring
  // that collides with ordinary copy, so its absence is not assertable.
  country: "ZZ-COUNTRY",
  timezone: "Europe/Madrid",
  maxGuests: 4,
  bedrooms: 2,
  bathrooms: 1,
  currentOperationalState: "AWAITING_CLEANING",
  defaultCheckInTime: "16:00:00",
  defaultCheckOutTime: "11:00:00",
  wifiName: "REDES11-WIFI",
  hasWifiPassword: true,
  status: "ACTIVE",
  createdAt: "1999-01-02T03:04:05Z",
  updatedAt: "1999-06-07T08:09:10Z",
};

function page(overrides: object = {}, rows: object[] = [ROW]) {
  return {
    data: rows,
    page: 1,
    perPage: 20,
    total: rows.length,
    totalPages: 1,
    ...overrides,
  };
}

function ok(pageData: object) {
  usePropertiesMock.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: pageData,
    refetch: vi.fn(),
  });
}

function failing(status: number) {
  usePropertiesMock.mockReturnValue({
    isPending: false,
    isError: true,
    error: new ApiError({ code: "X", message: "boom", status }),
    data: undefined,
    refetch: vi.fn(),
  });
}

describe("PropertiesView — the six columns, closed list (R1.2)", () => {
  it("renders exactly the six column headers, in order", () => {
    ok(page());
    renderView();
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      esProperties.columns.name,
      esProperties.columns.internalCode,
      esProperties.columns.city,
      esProperties.columns.capacity,
      esProperties.columns.operationalState,
      esProperties.columns.status,
    ]);
  });

  it("renders one table row per item, with six cells each", () => {
    ok(page({}, [ROW, { ...ROW, id: "property-2", name: "Pajaritos 8" }]));
    renderView();
    const rows = within(table()).getAllByRole("row");
    // One header row + two body rows.
    expect(rows).toHaveLength(3);
    for (const row of rows.slice(1)) {
      expect(within(row).getAllByRole("cell")).toHaveLength(6);
    }
  });

  it("shows the localized placeholder when the nullable city is null", () => {
    ok(page({}, [{ ...ROW, city: null }]));
    renderView();
    expect(
      within(table()).getByText(esProperties.cityEmpty),
    ).toBeInTheDocument();
  });
});

describe("PropertiesView — fields that must never reach the list (R1.6)", () => {
  it("renders none of the fiche fields, in either layout", () => {
    ok(page());
    const { container } = renderView();
    const text = container.textContent ?? "";
    for (const leaked of [
      "Calle Redes 11", // addressLine1
      "3ºB", // addressLine2
      "28051", // postalCode
      "ZZ-PROVINCE", // province — distinctive on purpose, see ROW
      "ZZ-COUNTRY", // country — distinctive on purpose, see ROW
      "true", // hasWifiPassword rendered as a boolean
      "false",
      "Europe/Madrid", // timezone
      "16:00", // defaultCheckInTime
      "11:00", // defaultCheckOutTime
      "REDES11-WIFI", // wifiName
      "ext-9999", // pmsExternalId
      "BEDS24", // pmsProvider
      "1999-01-02", // createdAt
      "1999-06-07", // updatedAt
    ]) {
      expect(text, `leaked ${leaked}`).not.toContain(leaked);
    }
  });

  it("renders the same six fields in the mobile layout, and nothing more", () => {
    ok(page());
    renderView();
    const card = cardList()[0];
    // The name is the card heading; the other five are label/value pairs.
    expect(within(card).getByRole("heading")).toHaveTextContent("Redes 11");
    const labels = within(card)
      .getAllByRole("term")
      .map((term) => term.textContent);
    expect(labels).toEqual([
      esProperties.columns.internalCode,
      esProperties.columns.city,
      esProperties.columns.capacity,
      esProperties.columns.operationalState,
      esProperties.columns.status,
    ]);
  });
});

describe("PropertiesView — capacity pluralizes (R6.1)", () => {
  it("uses the singular for one bedroom and one bathroom", () => {
    ok(page({}, [{ ...ROW, maxGuests: 1, bedrooms: 1, bathrooms: 1 }]));
    renderView();
    // The bug this pins: a single template with three counts produced
    // "1 huéspedes · 1 hab. · 1 baños".
    const cell = within(table()).getByText(/1 huésped\b/);
    expect(cell.textContent).toBe("1 huésped · 1 habitación · 1 baño");
  });

  it("uses the plural above one", () => {
    ok(page({}, [{ ...ROW, maxGuests: 4, bedrooms: 2, bathrooms: 3 }]));
    renderView();
    const cell = within(table()).getByText(/4 huéspedes/);
    expect(cell.textContent).toBe("4 huéspedes · 2 habitaciones · 3 baños");
  });
});

describe("PropertiesView — the row link (R1.5)", () => {
  it("links each row to the existing detail route, in both layouts", () => {
    ok(page());
    renderView();
    const links = screen.getAllByRole("link", {
      name: esProperties.row.openDetail.replace("{{name}}", "Redes 11"),
    });
    // One in the table, one in the card layout.
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "/properties/property-1");
    }
  });
});

describe("PropertiesView — operational state badge (R4)", () => {
  it("labels the badge from the dashboard namespace, not a local catalog", () => {
    ok(page());
    renderView();
    const label = (esDashboard.state as Record<string, string>)
      .AWAITING_CLEANING;
    expect(within(table()).getByText(label)).toBeInTheDocument();
    // The filter's option list reads the same catalog — that is the point of D10.
    expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
  });
});

describe("PropertiesView — pagination (R1.3)", () => {
  it("disables previous on the first page", () => {
    ok(page({ page: 1, totalPages: 3 }));
    renderView();
    expect(
      screen.getByRole("button", { name: esProperties.pagination.prev }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esProperties.pagination.next }),
    ).toBeEnabled();
  });

  it("disables next on the last page", () => {
    ok(page({ page: 3, totalPages: 3 }));
    renderView();
    expect(
      screen.getByRole("button", { name: esProperties.pagination.next }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esProperties.pagination.prev }),
    ).toBeEnabled();
  });

  it("offers no navigation at all when there is a single page (R1.3)", () => {
    // R1.3 conditions the navigation on `total_pages > 1`, so a bar with two
    // permanently-disabled arrows is dead furniture, not compliance.
    ok(page({ page: 1, totalPages: 1 }));
    renderView();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: esProperties.pagination.prev }),
    ).not.toBeInTheDocument();
  });

  it("degrades safely on a malformed page (data present, totalPages 0)", () => {
    ok(page({ page: 1, totalPages: 0 }, [ROW]));
    renderView();
    // No navigation, no crash, no negative page reachable.
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(within(table()).getAllByRole("row")).toHaveLength(2);
  });

  it("asks for the next page when next is activated", () => {
    ok(page({ page: 1, totalPages: 2 }));
    renderView();
    fireEvent.click(
      screen.getByRole("button", { name: esProperties.pagination.next }),
    );
    expect(usePropertiesMock.mock.calls.at(-1)?.[0]).toMatchObject({ page: 2 });
  });

  it("gives the pagination nav its own accessible name, not the page counter", () => {
    ok(page({ page: 1, totalPages: 2 }));
    renderView();
    expect(
      screen.getByRole("navigation", { name: esProperties.pagination.label }),
    ).toBeInTheDocument();
  });
});

describe("PropertiesView — filters reset pagination (R2.2)", () => {
  it("returns to page 1 when a filter changes from a later page", () => {
    ok(page({ page: 3, totalPages: 5 }));
    renderView();

    fireEvent.change(screen.getByLabelText(esProperties.filters.status), {
      target: { value: "INACTIVE" },
    });

    expect(usePropertiesMock.mock.calls.at(-1)?.[0]).toMatchObject({
      page: 1,
      status: "INACTIVE",
    });
  });

  it("emits the absence of a filter, not an empty string, when 'all' is picked", () => {
    ok(page());
    renderView();

    fireEvent.change(screen.getByLabelText(esProperties.filters.status), {
      target: { value: "" },
    });

    expect(usePropertiesMock.mock.calls.at(-1)?.[0]).not.toHaveProperty(
      "status",
    );
  });
});

describe("PropertiesView — the interface states (R3)", () => {
  it("shows the loading state while in flight (R3.1)", () => {
    usePropertiesMock.mockReturnValue({
      isPending: true,
      isError: false,
      error: null,
      data: undefined,
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a distinct forbidden state for 403 (R3.2)", () => {
    failing(403);
    renderView();
    expect(screen.getByText(esProperties.forbidden.title)).toBeInTheDocument();
  });

  it("shows a validation state for 422 without echoing the server body (R3.3)", () => {
    failing(422);
    const { container } = renderView();
    expect(screen.getByText(esProperties.validation.title)).toBeInTheDocument();
    expect(container.textContent ?? "").not.toContain("boom");
  });

  it("treats 401 as loading, never as an error (R3.4)", () => {
    failing(401);
    renderView();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText(esProperties.error.title)).not.toBeInTheDocument();
  });

  it("treats 404 on this list as the generic error, with a retry (R3.5)", () => {
    failing(404);
    renderView();
    expect(screen.getByText(esProperties.error.title)).toBeInTheDocument();
  });

  it("shows the empty state when the page carries no rows (R3.6)", () => {
    ok(page({ total: 0, totalPages: 0 }, []));
    renderView();
    expect(screen.getByText(esProperties.empty.title)).toBeInTheDocument();
    // No table, no cards, and no pagination controls over an empty page.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});

describe("PropertiesView — no hardcoded copy (R6.4)", () => {
  it("takes every visible string from the locale", () => {
    // Multi-page on purpose: with a single page the navigation is not rendered
    // at all (R1.3), so its copy could not be asserted here.
    ok(page({ page: 1, totalPages: 2 }));
    const { container } = renderView();
    const text = container.textContent ?? "";
    expect(text).toContain(esProperties.columns.name);
    expect(text).toContain(esProperties.pagination.prev);
    expect(text).toContain(esProperties.pagination.next);
    expect(text).toContain(esProperties.filters.all);
    expect(text).toContain(esProperties.filters.allStates);
  });
});

describe("PropertiesView — the create flow (R1.1, design D2/D12)", () => {
  it("shows the 'New property' button when MANAGE_PROPERTIES is granted", () => {
    useHasPermissionMock.mockReturnValue(true);
    ok(page());
    renderView();
    expect(
      screen.getByRole("button", { name: esProperties.newProperty }),
    ).toBeInTheDocument();
  });

  it("hides the 'New property' button without the permission", () => {
    useHasPermissionMock.mockReturnValue(false);
    ok(page());
    renderView();
    expect(
      screen.queryByRole("button", { name: esProperties.newProperty }),
    ).not.toBeInTheDocument();
  });

  it("opens the Sheet hosting CreatePropertyForm and closes it again", () => {
    useHasPermissionMock.mockReturnValue(true);
    ok(page());
    renderView();

    expect(screen.queryByText("create-property-form-stub")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: esProperties.newProperty }),
    );
    expect(
      screen.getByRole("heading", { name: esProperties.sheet.newPropertyTitle }),
    ).toBeInTheDocument();
    expect(screen.getByText("create-property-form-stub")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: esProperties.sheet.close }));
    expect(screen.queryByText("create-property-form-stub")).not.toBeInTheDocument();
  });
});

/**
 * Section 6 (tasks 6.2 and 6.3) for the create surface. The form inside the
 * `Sheet` is stubbed here, as everywhere in this file; its own accessibility and
 * keyboard contract is `features/properties/components/form/property-forms-a11y.test.tsx`,
 * and the rendered pixels are `property-forms-layout.browser.test.tsx`.
 */
describe("PropertiesView — the create Sheet's keyboard and layout contract (R4.3, R4.4)", () => {
  /**
   * Opens the create `Sheet` the way a keyboard user does — focus on the
   * trigger first, then activate it. The focus matters beyond realism: Radix's
   * `FocusScope` records `document.activeElement` at open time and restores it
   * on unmount, so a sheet opened from an unfocused trigger has nowhere to
   * return focus to and the assertion below would be measuring the harness.
   */
  function openSheet() {
    useHasPermissionMock.mockReturnValue(true);
    ok(page());
    renderView();
    const trigger = screen.getByRole("button", {
      name: esProperties.newProperty,
    });
    trigger.focus();
    fireEvent.click(trigger);
    return trigger;
  }

  it("closes on Escape and returns focus to the trigger (task 6.2)", async () => {
    const trigger = openSheet();

    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    // Half the contract, and the half a "did it close?" check misses: a
    // keyboard user who escapes out of the sheet lands back on the control
    // they opened it from, not at the top of the document. Radix restores it
    // through `FocusScope`'s `onUnmountAutoFocus`, asynchronously — hence the
    // `waitFor` rather than a bare read.
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("gives the 'New property' trigger a 44×44 target (task 6.1)", () => {
    useHasPermissionMock.mockReturnValue(true);
    ok(page());
    renderView();
    // The class, not the pixels: jsdom does no layout. Measured for real in
    // `property-forms-layout.browser.test.tsx`.
    expect(
      screen.getByRole("button", { name: esProperties.newProperty }),
    ).toHaveClass("tap-target");
  });

  it("scrolls its own content rather than clipping it (task 6.3, R4.4)", async () => {
    /*
     * `SheetContent`'s `side="right"` variant is `inset-y-0 … h-full` — pinned
     * to the viewport's height — and declares no overflow behaviour of its own,
     * so a twenty-field form inside it renders past the bottom edge with no way
     * to reach the rest: not a scrollbar short, unreachable. The fix is the
     * caller's `overflow-y-auto`, the same one
     * `features/notifications/components/notification-inbox-sheet.tsx` carries.
     * Asserted on the class because jsdom computes no scroll height either.
     */
    openSheet();
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveClass("overflow-y-auto");
    expect(dialog).toHaveClass("h-full");
  });

  it("has no axe violations with the sheet open (task 6.1)", async () => {
    openSheet();
    const dialog = await screen.findByRole("dialog");
    // Scoped to the dialog for the reason `topbar-overflow-sheet.test.tsx`
    // records: a component test renders no landmarks, so a document-wide scan
    // reports `region` against the portal rather than against this surface.
    expect(await getA11yViolations(dialog)).toEqual([]);
  });
});
