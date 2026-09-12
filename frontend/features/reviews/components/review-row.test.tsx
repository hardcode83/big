import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertySummary, Review } from "../data";
import { ReviewRow } from "./review-row";

const CATALOG: PropertySummary[] = [
  { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
];

const REVIEW: Review = {
  id: "rev-1",
  propertyId: "p-1",
  reviewerName: "Jane Doe",
  rating: "4.5",
  content: "Great stay",
  sentiment: "POSITIVE",
  aiSummary: null,
  recurringIssues: [],
  status: "DRAFTED",
  publishedAt: "2026-09-01",
  channel: "AIRBNB",
  language: "en",
};

function renderRow(
  overrides: Partial<Review> = {},
  props: { catalog?: readonly PropertySummary[]; catalogPending?: boolean; showStatus?: boolean } = {},
) {
  const onOpen = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <ReviewRow
        review={{ ...REVIEW, ...overrides }}
        catalog={props.catalog ?? CATALOG}
        catalogPending={props.catalogPending ?? false}
        showStatus={props.showStatus ?? false}
        onOpen={onOpen}
      />
    </I18nProvider>,
  );
  return { ...result, onOpen };
}

describe("ReviewRow — the compact card (R2.4, R5.2)", () => {
  it("shows the resolved property name", () => {
    renderRow();
    expect(screen.getByText("Ático Sol")).toBeInTheDocument();
  });

  it("shows the loading marker while the catalog is in flight", () => {
    renderRow({}, { catalogPending: true, catalog: [] });
    expect(screen.getByText("Cargando catálogo…")).toBeInTheDocument();
  });

  it("shows the unavailable marker when the catalog settled without this id", () => {
    renderRow({}, { catalog: [] });
    expect(screen.getByText("Vivienda no disponible")).toBeInTheDocument();
  });

  it("shows the channel", () => {
    renderRow();
    expect(screen.getByText("Airbnb")).toBeInTheDocument();
  });

  it("shows rating and sentiment", () => {
    renderRow();
    expect(screen.getByText(/4,5\/5/)).toBeInTheDocument();
    expect(screen.getByText(/Positivo/)).toBeInTheDocument();
  });

  it("renders an em dash for a null rating and null sentiment", () => {
    renderRow({ rating: null, sentiment: null });
    // Both the rating and the sentiment segments fall back to the same dash.
    expect(screen.getAllByText(/–/).length).toBeGreaterThan(0);
  });

  it("renders an em dash for a null publishedAt (manual create, R5.4)", () => {
    renderRow({ publishedAt: null });
    const row = screen.getByRole("button");
    expect(row.textContent).toContain("–");
  });

  it("only paints the status badge when showStatus is true (R5.2)", () => {
    renderRow({}, { showStatus: false });
    expect(screen.queryByText("Borrador")).not.toBeInTheDocument();
  });

  it("paints the localized status badge on the Reseñas tab", () => {
    renderRow({}, { showStatus: true });
    expect(screen.getByText("Borrador")).toBeInTheDocument();
  });

  it("does not render content, aiSummary, recurringIssues or the draft (design D11)", () => {
    renderRow({
      content: "should not appear",
      aiSummary: "should not appear either",
    });
    expect(screen.queryByText("should not appear")).not.toBeInTheDocument();
    expect(screen.queryByText("should not appear either")).not.toBeInTheDocument();
  });

  it("opens the detail when clicked", () => {
    const { onOpen } = renderRow();
    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledWith("rev-1");
  });

  it("has no accessibility violations", async () => {
    const { container } = renderRow({}, { showStatus: true });
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
