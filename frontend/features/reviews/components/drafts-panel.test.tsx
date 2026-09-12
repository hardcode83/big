import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { DraftsPanel, type DraftsPanelProps } from "./drafts-panel";

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
  status: "DRAFTED" as const,
  publishedAt: "2026-09-01",
  channel: "AIRBNB" as const,
  language: "en",
};

function page(items: unknown[], overrides: Record<string, number> = {}) {
  return { items, total: items.length, page: 1, perPage: 20, totalPages: items.length === 0 ? 0 : 1, ...overrides };
}

function renderPanel(overrides: Partial<DraftsPanelProps> = {}) {
  const onOpenCreateDialog = vi.fn();
  const onOpenRow = vi.fn();
  const onConfirm = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <DraftsPanel
        catalog={overrides.catalog ?? CATALOG}
        catalogPending={overrides.catalogPending ?? false}
        canCreate={overrides.canCreate ?? true}
        createDialogOpen={overrides.createDialogOpen ?? false}
        onOpenCreateDialog={onOpenCreateDialog}
        isMutationPending={overrides.isMutationPending ?? false}
        pendingReviewId={overrides.pendingReviewId ?? null}
        onOpenRow={onOpenRow}
        role={overrides.role ?? "owner"}
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

describe("DraftsPanel — always fixed to status=DRAFTED (R2.1)", () => {
  it("passes status: DRAFTED to the query regardless of the store", () => {
    renderPanel();
    expect(useReviewsList).toHaveBeenCalledWith(
      expect.objectContaining({ status: "DRAFTED" }),
      1,
    );
  });

  it("does not render a status selector", () => {
    renderPanel();
    expect(screen.queryByLabelText("Estado")).not.toBeInTheDocument();
  });
});

describe("DraftsPanel — filters flow through to the query (R2.1)", () => {
  it("includes propertyId, channel, sentiment, rating and dates once chosen", () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "GOOGLE" } });
    fireEvent.change(screen.getByLabelText("Sentimiento"), { target: { value: "POSITIVE" } });
    fireEvent.change(screen.getByLabelText("Mínimo"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Máximo"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2026-09-30" } });

    expect(useReviewsList).toHaveBeenLastCalledWith(
      {
        propertyId: "p-1",
        channel: "GOOGLE",
        sentiment: "POSITIVE",
        ratingMin: 3,
        ratingMax: 5,
        dateFrom: "2026-09-01",
        dateTo: "2026-09-30",
        status: "DRAFTED",
      },
      1,
    );
  });

  it("writes only to the drafts slice, never the reviews slice", () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    expect(useReviewsUiStore.getState().drafts.propertyId).toBe("p-1");
    expect(useReviewsUiStore.getState().reviews.propertyId).toBeUndefined();
  });
});

describe("DraftsPanel — list states (R2.3)", () => {
  it("shows the loading copy", () => {
    useReviewsList.mockReturnValue({ isPending: true, isError: false, data: undefined });
    renderPanel();
    expect(screen.getByText("Cargando…")).toBeInTheDocument();
  });

  it("shows the read-error copy chosen by status, never the backend's own words", () => {
    useReviewsList.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "no drafts for you", status: 403 }),
      data: undefined,
    });
    const { container } = renderPanel();
    expect(
      screen.getByText("No tienes permiso para ver estas reseñas."),
    ).toBeInTheDocument();
    expect(container.textContent).not.toContain("no drafts for you");
  });

  it("shows the drafts-specific empty copy when total is 0", () => {
    useReviewsList.mockReturnValue({ isPending: false, isError: false, data: page([]) });
    renderPanel();
    expect(screen.getByText("Sin borradores pendientes")).toBeInTheDocument();
  });

  it("renders the rows the query returned, without the status badge (R2.4)", () => {
    useReviewsList.mockReturnValue({ isPending: false, isError: false, data: page([REVIEW]) });
    renderPanel();
    expect(screen.getByRole("button", { name: /Ático Sol/ })).toBeInTheDocument();
    expect(screen.queryByText("Borrador")).not.toBeInTheDocument();
  });
});

describe("DraftsPanel — Add review is gated at the parent (D15, R7.1, R7.4)", () => {
  it("shows the button when createDialogOpen is false and canCreate is true", () => {
    renderPanel({ createDialogOpen: false, canCreate: true });
    expect(screen.getByRole("button", { name: "Añadir reseña" })).toBeInTheDocument();
  });

  it("hides the button while the dialog is open", () => {
    renderPanel({ createDialogOpen: true });
    expect(screen.queryByRole("button", { name: "Añadir reseña" })).not.toBeInTheDocument();
  });

  it("does not render the button at all without CREATE_REVIEW_UI (R7.1)", () => {
    renderPanel({ canCreate: false });
    expect(screen.queryByRole("button", { name: "Añadir reseña" })).not.toBeInTheDocument();
  });
});
