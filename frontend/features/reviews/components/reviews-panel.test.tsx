import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { ReviewsPanel, type ReviewsPanelProps } from "./reviews-panel";

const useReviewsList = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-reviews-data", () => ({ useReviewsList }));

const CATALOG: PropertySummary[] = [
  { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
];

const REVIEW = {
  id: "rev-1",
  propertyId: "p-1",
  reviewerName: "Jane",
  rating: "4.0",
  content: "ok",
  sentiment: "POSITIVE" as const,
  aiSummary: null,
  recurringIssues: [],
  status: "APPROVED" as const,
  publishedAt: "2026-09-01",
  channel: "AIRBNB" as const,
  language: "en",
};

function page(items: unknown[], overrides: Record<string, number> = {}) {
  return { items, total: items.length, page: 1, perPage: 20, totalPages: items.length === 0 ? 0 : 1, ...overrides };
}

function renderPanel(overrides: Partial<ReviewsPanelProps> = {}) {
  const onOpenCreateDialog = vi.fn();
  const onOpenRow = vi.fn();
  const onConfirm = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <ReviewsPanel
        catalog={overrides.catalog ?? CATALOG}
        catalogPending={overrides.catalogPending ?? false}
        canCreate={overrides.canCreate ?? true}
        createDialogOpen={overrides.createDialogOpen ?? false}
        onOpenCreateDialog={onOpenCreateDialog}
        onOpenRow={onOpenRow}
        role={overrides.role ?? "owner"}
        isMutationPending={overrides.isMutationPending ?? false}
        pendingReviewId={overrides.pendingReviewId ?? null}
        onConfirm={onConfirm}
      />
    </I18nProvider>,
  );
  return { ...result, onOpenCreateDialog, onOpenRow, onConfirm };
}

beforeEach(() => {
  useReviewsUiStore.getState().reset();
  useReviewsList.mockReset().mockReturnValue({ isPending: false, isError: false, data: page([]) });
});

describe("ReviewsPanel — status is a selector, unlike Borradores (R5.1)", () => {
  it("renders a status selector with all five values", () => {
    renderPanel();
    const options = Array.from(
      screen.getByLabelText("Estado").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(options).toEqual([
      "Todos los estados",
      "Nueva",
      "Borrador",
      "Aprobada",
      "Publicada manualmente",
      "Ignorada",
    ]);
  });

  it("includes the chosen status in the query, alongside the other filters", () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "BOOKING" } });
    fireEvent.change(screen.getByLabelText("Sentimiento"), { target: { value: "NEGATIVE" } });
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "APPROVED" } });
    fireEvent.change(screen.getByLabelText("Mínimo"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Máximo"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-01-01" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-01-31" } });

    expect(useReviewsList).toHaveBeenLastCalledWith(
      {
        propertyId: "p-1",
        channel: "BOOKING",
        sentiment: "NEGATIVE",
        status: "APPROVED",
        ratingMin: 1,
        ratingMax: 3,
        dateFrom: "2026-01-01",
        dateTo: "2026-01-31",
      },
      1,
    );
  });

  it("writes the chosen status only to the reviews slice", () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "IGNORED" } });
    expect(useReviewsUiStore.getState().reviews.status).toBe("IGNORED");
  });
});

describe("ReviewsPanel — list states (R5.2)", () => {
  it("shows the read-error copy, never the backend's own words", () => {
    useReviewsList.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "no reviews for you", status: 403 }),
      data: undefined,
    });
    const { container } = renderPanel();
    expect(
      screen.getByText("No tienes permiso para ver estas reseñas."),
    ).toBeInTheDocument();
    expect(container.textContent).not.toContain("no reviews for you");
  });

  it("shows the reviews empty copy (distinct from the drafts one)", () => {
    renderPanel();
    expect(screen.getByText("Sin reseñas")).toBeInTheDocument();
  });

  it("renders the row with its status badge (R5.2)", () => {
    useReviewsList.mockReturnValue({ isPending: false, isError: false, data: page([REVIEW]) });
    renderPanel();
    expect(screen.getByRole("button", { name: /Ático Sol/ })).toHaveTextContent(
      "Aprobada",
    );
  });
});

describe("ReviewsPanel — Add review is gated at the parent (D15, R7.1, R7.4)", () => {
  it("does not render the button at all without CREATE_REVIEW_UI (R7.1)", () => {
    renderPanel({ canCreate: false });
    expect(screen.queryByRole("button", { name: "Añadir reseña" })).not.toBeInTheDocument();
  });
});

describe("ReviewsPanel — row actions per status and role (D5)", () => {
  it("offers only Marcar como publicada... row buttons never include MARK_POSTED or EDIT (D12)", () => {
    useReviewsList.mockReturnValue({ isPending: false, isError: false, data: page([REVIEW]) });
    renderPanel({ role: "owner" });
    expect(screen.queryByRole("button", { name: "Marcar como publicada" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar borrador" })).not.toBeInTheDocument();
  });

  it("opens the detail when a row is clicked", () => {
    useReviewsList.mockReturnValue({ isPending: false, isError: false, data: page([REVIEW]) });
    const { onOpenRow } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Ático Sol/ }));
    expect(onOpenRow).toHaveBeenCalledWith("rev-1");
  });
});
