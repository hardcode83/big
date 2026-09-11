import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { render, screen } from "@/test/render";
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
vi.mock("@/features/properties", () => ({
  EditPropertyForm: ({ propertyId }: { propertyId: string }) => (
    <div>edit-property-form-stub:{propertyId}</div>
  ),
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
  useHasPermissionMock.mockReturnValue(true);
  usePropertyTimeline.mockReturnValue({
    isPending: false,
    isError: false,
    data: { data: [], total: 0, page: 1, per_page: 0, total_pages: 0 },
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
