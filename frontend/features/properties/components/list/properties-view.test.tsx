import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esDashboard from "@/locales/es/dashboard.json";
import esProperties from "@/locales/es/properties.json";
import { fireEvent, render, screen, within } from "@/test/render";

const usePropertiesMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-properties", () => ({
  useProperties: usePropertiesMock,
}));

import { PropertiesView } from "./properties-view";

function renderView() {
  return render(
    <I18nProvider locale="es">
      <PropertiesView />
    </I18nProvider>,
  );
}

const ROW = {
  id: "property-1",
  name: "Redes 11",
  internalCode: "REDES11",
  pmsProvider: "BEDS24",
  pmsExternalId: "ext-9999",
  addressLine1: "Calle Redes 11",
  addressLine2: "3ºB",
  city: "Madrid",
  province: "Madrid",
  postalCode: "28051",
  country: "ES",
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
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-02T09:00:00Z",
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

describe("PropertiesView — the six columns, closed list (R1.2, R1.6)", () => {
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

  it("renders one row per item with its six cells", () => {
    ok(page({}, [ROW, { ...ROW, id: "property-2", name: "Pajaritos 8" }]));
    renderView();
    // One header row + two body rows.
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("Redes 11")).toBeInTheDocument();
    expect(screen.getByText("Pajaritos 8")).toBeInTheDocument();
  });

  it("does NOT render any field outside the six columns (R1.6, R5.3)", () => {
    ok(page());
    const { container } = renderView();
    const text = container.textContent ?? "";
    // Fiche data that travels in the payload but must not reach the list.
    for (const leaked of [
      "Calle Redes 11", // addressLine1
      "3ºB", // addressLine2
      "28051", // postalCode
      "Europe/Madrid", // timezone
      "16:00", // defaultCheckInTime
      "11:00", // defaultCheckOutTime
      "REDES11-WIFI", // wifiName
      "ext-9999", // pmsExternalId
      "BEDS24", // pmsProvider
      "2026-08-01", // createdAt
    ]) {
      expect(text, `leaked ${leaked}`).not.toContain(leaked);
    }
  });

  it("shows the localized placeholder when the nullable city is null", () => {
    ok(page({}, [{ ...ROW, city: null }]));
    renderView();
    expect(screen.getByText(esProperties.cityEmpty)).toBeInTheDocument();
  });
});

describe("PropertiesView — the row link (R1.5)", () => {
  it("links each row to the existing detail route", () => {
    ok(page());
    renderView();
    const link = screen.getByRole("link", {
      name: esProperties.row.openDetail.replace("{{name}}", "Redes 11"),
    });
    expect(link).toHaveAttribute("href", "/properties/property-1");
  });
});

describe("PropertiesView — operational state badge (R4)", () => {
  it("labels the badge from the dashboard namespace, not a local catalog", () => {
    ok(page());
    renderView();
    const label = (esDashboard.state as Record<string, string>)
      .AWAITING_CLEANING;
    // Scoped to the table on purpose: the same eleven labels also appear as
    // `<option>`s in the operational-state filter, so an unscoped query finds
    // two nodes. That duplication is correct — both read the same catalog,
    // which is the point of D10 — but the assertion has to name which one.
    const table = screen.getByRole("table");
    expect(
      within(table).getByText(label),
      "the row badge must carry the dashboard-namespace label",
    ).toBeInTheDocument();
    // And the filter option carries it too, from the same catalog.
    expect(
      screen.getByRole("option", { name: label }),
    ).toBeInTheDocument();
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

  it("asks for the next page when next is activated", () => {
    ok(page({ page: 1, totalPages: 2 }));
    renderView();
    fireEvent.click(
      screen.getByRole("button", { name: esProperties.pagination.next }),
    );
    // The hook is called again with page 2.
    const lastCall = usePropertiesMock.mock.calls.at(-1);
    expect(lastCall?.[0]).toMatchObject({ page: 2 });
  });
});

describe("PropertiesView — filters reset pagination (R2.2)", () => {
  it("returns to page 1 when a filter changes from a later page", () => {
    // The bug this pins: filtering from page 3 could request a page the
    // filtered set does not have, which comes back as an empty `data` the
    // screen cannot tell apart from "nothing matches".
    ok(page({ page: 3, totalPages: 5 }));
    renderView();

    fireEvent.change(screen.getByLabelText(esProperties.filters.status), {
      target: { value: "INACTIVE" },
    });

    const lastCall = usePropertiesMock.mock.calls.at(-1);
    expect(lastCall?.[0]).toMatchObject({ page: 1, status: "INACTIVE" });
  });

  it("emits the absence of a filter, not an empty string, when 'all' is picked", () => {
    ok(page());
    renderView();

    fireEvent.change(screen.getByLabelText(esProperties.filters.status), {
      target: { value: "" },
    });

    const lastCall = usePropertiesMock.mock.calls.at(-1);
    expect(lastCall?.[0]).not.toHaveProperty("status");
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
  });
});

describe("PropertiesView — no hardcoded copy (R6.4)", () => {
  it("takes every visible string from the locale", () => {
    ok(page());
    const { container } = renderView();
    const text = container.textContent ?? "";
    // The locale values are present; nothing is spelled in the component.
    expect(text).toContain(esProperties.columns.name);
    expect(text).toContain(esProperties.pagination.prev);
    expect(text).toContain(esProperties.filters.all);
  });
});
