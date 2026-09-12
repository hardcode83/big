import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
  within,
} from "@/test/render";

import type { Review, ReviewsDataSource } from "../data";
import { useReviewsUiStore } from "../state/use-reviews-ui-store";
import { ReviewsView } from "./reviews-view";

const listReviews = vi.hoisted(() => vi.fn());
const getReview = vi.hoisted(() => vi.fn());
const getDraft = vi.hoisted(() => vi.fn());
const createReview = vi.hoisted(() => vi.fn());
const respondToReview = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const useHasPermission = vi.hoisted(() => vi.fn(() => true));
const authUser = vi.hoisted(() => ({
  current: { tenant_id: "tenant-1", role: "TENANT_OWNER" as string },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: authUser.current }),
  useHasPermission,
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getReviewsDataSource: (): ReviewsDataSource => ({
    listReviews,
    getReview,
    getDraft,
    createReview,
    respondToReview,
    listProperties,
  }),
}));

const REVIEW: Review = {
  id: "rev-1",
  propertyId: "p-1",
  reviewerName: "Jane",
  rating: "4.5",
  content: "Great place",
  sentiment: "POSITIVE",
  aiSummary: null,
  recurringIssues: [],
  status: "DRAFTED",
  publishedAt: "2026-09-01",
  channel: "AIRBNB",
  language: "en",
};

function page<T>(items: T[]) {
  return {
    items,
    total: items.length,
    page: 1,
    per_page: 20,
  };
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<ReviewsView />, { wrapper: Wrapper });
}

const tab = (name: string) => screen.getByRole("tab", { name });

beforeEach(() => {
  useReviewsUiStore.getState().reset();
  authUser.current = { tenant_id: "tenant-1", role: "TENANT_OWNER" };
  useHasPermission.mockReturnValue(true);
  listReviews.mockReset().mockResolvedValue(page([REVIEW]));
  getReview.mockReset().mockResolvedValue(REVIEW);
  getDraft.mockReset().mockResolvedValue({
    reviewId: "rev-1",
    draftContent: "Thanks!",
    language: "en",
  });
  createReview.mockReset();
  respondToReview.mockReset().mockResolvedValue({ ...REVIEW, status: "APPROVED" });
  listProperties
    .mockReset()
    .mockResolvedValue([{ id: "p-1", name: "Ático Sol", internal_code: "MAD-01" }]);
});

describe("ReviewsView — tabs (R1.1, R1.3, R2.1, R5.1)", () => {
  it("opens on Borradores by default", async () => {
    renderView();
    await waitFor(() =>
      expect(tab("Borradores")).toHaveAttribute("aria-selected", "true"),
    );
  });

  it("does not query the reviews tab until it is opened", async () => {
    renderView();
    await waitFor(() => expect(listReviews).toHaveBeenCalledTimes(1));

    fireEvent.click(tab("Reseñas"));
    await waitFor(() => expect(listReviews).toHaveBeenCalledTimes(2));
  });

  it("keeps each tab's filters and page independent", async () => {
    renderView();
    await waitFor(() => expect(listReviews).toHaveBeenCalled());

    useReviewsUiStore.getState().setDraftsPage(3);
    fireEvent.click(tab("Reseñas"));
    await waitFor(() => expect(listReviews).toHaveBeenCalledTimes(2));
    expect(useReviewsUiStore.getState().reviews.page).toBe(1);

    fireEvent.click(tab("Borradores"));
    expect(useReviewsUiStore.getState().drafts.page).toBe(3);
  });
});

describe("ReviewsView — the queue (R2.3, R2.4)", () => {
  it("renders the row the source returned", async () => {
    renderView();
    expect(await screen.findByRole("button", { name: /Ático Sol/ })).toBeInTheDocument();
  });

  it("renders the empty state and no pagination when total is 0 (R2.3)", async () => {
    listReviews.mockResolvedValue(page([]));
    renderView();
    expect(await screen.findByText("Sin borradores pendientes")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});

describe("ReviewsView — one write in flight (R3.3, R4.3, design D9)", () => {
  it("disables every row's decision buttons while a decision is flying", async () => {
    respondToReview.mockImplementation(() => new Promise(() => {}));
    listReviews.mockResolvedValue(page([REVIEW, { ...REVIEW, id: "rev-2" }]));
    renderView();

    const approveButtons = await screen.findAllByRole("button", { name: "Aprobar" });
    fireEvent.click(approveButtons[0]!);
    fireEvent.click(screen.getAllByRole("button", { name: "Confirmar" })[0]!);

    await waitFor(() => expect(screen.getByText("Enviando…")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Aprobar" })).toBeDisabled();
  });

  it("does NOT disable the filter controls while a write is in flight", async () => {
    respondToReview.mockImplementation(() => new Promise(() => {}));
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() => expect(screen.getByText("Enviando…")).toBeInTheDocument());
    for (const label of ["Vivienda", "Canal", "Sentimiento"]) {
      expect(screen.getByLabelText(label)).toBeEnabled();
    }
  });
});

describe("ReviewsView — the shared error banner (R3.5, R3.6, R3.7)", () => {
  it("shows the 409 copy of its own, distinct from the generic one", async () => {
    respondToReview.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "wrong state", status: 409 }),
    );
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(
      await screen.findByText(
        "Esa reseña ya no está en el estado que creías. Vuelve a cargar la lista.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a 403 as an error, never as success", async () => {
    respondToReview.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    const region = await screen.findByRole("status");
    expect(region).toHaveTextContent(
      "No tienes permiso para decidir sobre esta reseña.",
    );
  });

  it("never paints the backend's own message", async () => {
    respondToReview.mockRejectedValue(
      new ApiError({
        code: "CONFLICT",
        message: "Review 7f3c is not in state DRAFTED",
        status: 409,
      }),
    );
    const { container } = renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await screen.findByRole("status");
    expect(container.textContent).not.toContain("7f3c");
    expect(container.textContent).not.toContain("is not in state");
  });
});

describe("ReviewsView — the catalog does not take the queue down (R2.8)", () => {
  it("renders the queue with degraded identity when the catalog fails", async () => {
    listProperties.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    renderView();

    expect(await screen.findByText("Vivienda no disponible")).toBeInTheDocument();
    expect(
      screen.queryByText("No se pudieron cargar los borradores"),
    ).not.toBeInTheDocument();
  });
});

describe("ReviewsView — reading without permission (R7.3, D15)", () => {
  it("shows the localized 403 copy rather than a blank screen", async () => {
    listReviews.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    renderView();

    expect(
      await screen.findByText("No tienes permiso para ver estas reseñas."),
    ).toBeInTheDocument();
  });

  it("hides Add review without CREATE_REVIEW_UI", async () => {
    useHasPermission.mockReturnValue(false);
    renderView();

    await screen.findByRole("button", { name: /Ático Sol/ });
    expect(
      screen.queryByRole("button", { name: "Añadir reseña" }),
    ).not.toBeInTheDocument();
  });
});

describe("ReviewsView — role gates decisions but not Edit (D5, D15)", () => {
  it("the manager sees Edit on a DRAFTED row's detail but no Approve/Ignore row buttons", async () => {
    authUser.current = { tenant_id: "tenant-1", role: "PROPERTY_MANAGER" };
    renderView();

    const row = await screen.findByRole("button", { name: /Ático Sol/ });
    expect(screen.queryByRole("button", { name: "Aprobar" })).not.toBeInTheDocument();

    fireEvent.click(row);
    expect(
      await screen.findByRole("button", { name: "Editar borrador" }),
    ).toBeInTheDocument();
  });
});

describe("ReviewsView — the detail overlay (R6.1)", () => {
  it("opens the detail on row click and shows the guest text", async () => {
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Ático Sol/ }));
    expect(await screen.findByText("Great place")).toBeInTheDocument();
  });

  it("shows a loading marker while the detail query is in flight", async () => {
    getReview.mockImplementation(() => new Promise(() => {}));
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Ático Sol/ }));
    expect(await screen.findByText("Cargando detalle…")).toBeInTheDocument();
  });

  it("shows the read-error copy when the detail query fails", async () => {
    getReview.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "gone", status: 404 }),
    );
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Ático Sol/ }));
    expect(await screen.findByText("La reseña ya no existe.")).toBeInTheDocument();
  });

  it("marks a review as posted through the dialog, once approved", async () => {
    listReviews.mockResolvedValue(page([{ ...REVIEW, status: "APPROVED" }]));
    getReview.mockResolvedValue({ ...REVIEW, status: "APPROVED" });
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Ático Sol/ }));

    fireEvent.click(await screen.findByRole("button", { name: "Marcar como publicada" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Confirmar" })[0]!);

    await waitFor(() =>
      expect(respondToReview).toHaveBeenCalledWith("tenant-1", {
        reviewId: "rev-1",
        action: "MARK_POSTED",
      }),
    );
  });
});

describe("ReviewsView — creating a review (R5.3, R5.5)", () => {
  it("opens the dialog, submits, and closes it on success", async () => {
    createReview.mockResolvedValue({ ...REVIEW, id: "rev-2" });
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Añadir reseña" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.change(within(dialog).getByLabelText("Vivienda"), {
      target: { value: "p-1" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Crear reseña" }));

    await waitFor(() => expect(createReview).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
  });

  it("keeps the dialog open and shows the error inside it on failure", async () => {
    createReview.mockRejectedValue(
      new ApiError({ code: "UNPROCESSABLE_ENTITY", message: "bad", status: 422 }),
    );
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Añadir reseña" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.change(within(dialog).getByLabelText("Vivienda"), {
      target: { value: "p-1" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Crear reseña" }));

    expect(
      await within(dialog).findByText("Los datos enviados no son válidos."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Crear reseña" }),
    ).toBeInTheDocument();
  });
});

describe("ReviewsView — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderView();
    await screen.findByRole("button", { name: /Ático Sol/ });
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
