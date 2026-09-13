import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { Review, ReviewDraft } from "../data";
import type { ReviewerRole } from "../lib/review-actions";
import { ReviewDetail } from "./review-detail";

const REVIEW: Review = {
  id: "rev-1",
  propertyId: "p-1",
  reviewerName: "Jane Doe",
  rating: "4.5",
  content: "Wifi <b>fatal</b>, never again",
  sentiment: "NEGATIVE",
  aiSummary: "Guest complained about wifi",
  recurringIssues: ["WIFI"],
  status: "DRAFTED",
  publishedAt: "2026-09-01",
  channel: "AIRBNB",
  language: "en",
};

const DRAFT: ReviewDraft = {
  reviewId: "rev-1",
  draftContent: "Thanks for the feedback.",
  language: "en",
};

function renderDetail(overrides: {
  review?: Review;
  draft?: ReviewDraft | null;
  role?: ReviewerRole;
  isBusy?: boolean;
  isPending?: boolean;
} = {}) {
  const onClose = vi.fn();
  const onConfirm = vi.fn();
  const onMarkPosted = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <ReviewDetail
        review={overrides.review ?? REVIEW}
        draft={"draft" in overrides ? overrides.draft ?? null : DRAFT}
        isBusy={overrides.isBusy ?? false}
        isPending={overrides.isPending ?? false}
        role={overrides.role ?? "owner"}
        onClose={onClose}
        onConfirm={onConfirm}
        onMarkPosted={onMarkPosted}
      />
    </I18nProvider>,
  );
  return { ...result, onClose, onConfirm, onMarkPosted };
}

describe("ReviewDetail — the preview fields (R6.1, R6.2, R6.3, R6.4)", () => {
  it("shows the guest's text as literal text, never as HTML (D11)", () => {
    renderDetail();
    expect(screen.getByText("Wifi <b>fatal</b>, never again")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
  });

  it("shows rating, channel, reviewer, sentiment, ai summary and recurring issues", () => {
    renderDetail();
    expect(screen.getByText(/4,5\/5/)).toBeInTheDocument();
    expect(screen.getByText(/Airbnb/)).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();
    expect(screen.getByText(/Negativo/)).toBeInTheDocument();
    expect(screen.getByText("Guest complained about wifi")).toBeInTheDocument();
    expect(screen.getByText("Wifi")).toBeInTheDocument();
  });

  it("closes on the close button", () => {
    const { onClose } = renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("omits null fields rather than rendering an empty label", () => {
    renderDetail({
      review: { ...REVIEW, reviewerName: null, sentiment: null, aiSummary: null, recurringIssues: [] },
    });
    expect(screen.queryByText(/Huésped/)).not.toBeInTheDocument();
  });
});

describe("ReviewDetail — the draft and its edit flow (R3.3)", () => {
  it("shows the current draft content", () => {
    renderDetail();
    expect(screen.getByText("Thanks for the feedback.")).toBeInTheDocument();
  });

  it("renders no draft card when the draft is null (IGNORED reviews)", () => {
    renderDetail({ draft: null });
    expect(screen.queryByText("Guardar cambios")).not.toBeInTheDocument();
  });

  it("opens an editable textarea seeded with the current draft", () => {
    renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "Editar borrador" }));
    expect(screen.getByRole("textbox")).toHaveValue("Thanks for the feedback.");
  });

  it("submits EDIT with the trimmed value on save", () => {
    const { onConfirm } = renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "Editar borrador" }));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  Updated response.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
    expect(onConfirm).toHaveBeenCalledWith({
      reviewId: "rev-1",
      action: "EDIT",
      draftContent: "Updated response.",
    });
  });

  it("does not submit an empty (or whitespace-only) edit", () => {
    const { onConfirm } = renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "Editar borrador" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("cancels editing without submitting", () => {
    const { onConfirm } = renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "Editar borrador" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar edición" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText("Thanks for the feedback.")).toBeInTheDocument();
  });
});

describe("ReviewDetail — role gates Edit and Mark-Posted through legalActions (D5, D15)", () => {
  it("shows Edit but not Mark-Posted to the owner on DRAFTED", () => {
    renderDetail({ role: "owner", review: { ...REVIEW, status: "DRAFTED" } });
    expect(screen.getByRole("button", { name: "Editar borrador" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Marcar como publicada" }),
    ).not.toBeInTheDocument();
  });

  it("shows Edit to the manager on DRAFTED too", () => {
    renderDetail({ role: "manager", review: { ...REVIEW, status: "DRAFTED" } });
    expect(screen.getByRole("button", { name: "Editar borrador" })).toBeInTheDocument();
  });

  it("shows only Mark-Posted to the owner on APPROVED", () => {
    renderDetail({
      role: "owner",
      review: { ...REVIEW, status: "APPROVED" },
      draft: { ...DRAFT },
    });
    expect(
      screen.getByRole("button", { name: "Marcar como publicada" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Editar borrador" }),
    ).not.toBeInTheDocument();
  });

  it("hides Mark-Posted from the manager on APPROVED (owner-only per D15)", () => {
    renderDetail({ role: "manager", review: { ...REVIEW, status: "APPROVED" } });
    expect(
      screen.queryByRole("button", { name: "Marcar como publicada" }),
    ).not.toBeInTheDocument();
  });
});

describe("ReviewDetail — Mark-Posted opens the dialog, does not duplicate row buttons", () => {
  it("opens the dialog and calls onMarkPosted on confirm", () => {
    const { onMarkPosted } = renderDetail({ review: { ...REVIEW, status: "APPROVED" } });
    fireEvent.click(screen.getByRole("button", { name: "Marcar como publicada" }));
    expect(screen.getByText("Vas a registrar que ya publicaste esta respuesta en el canal correspondiente. Esta acción no se puede deshacer desde esta pantalla.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Confirmar" })[0]!);
    expect(onMarkPosted).toHaveBeenCalledWith("rev-1");
  });

  it("never renders Approve/Ignore here — those live in the row's ReviewActions", () => {
    renderDetail({ review: { ...REVIEW, status: "DRAFTED" } });
    expect(screen.queryByRole("button", { name: "Aprobar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ignorar" })).not.toBeInTheDocument();
  });
});

describe("ReviewDetail — while a write is in flight (design D9)", () => {
  it("shows the sending text", () => {
    renderDetail({ isPending: true });
    expect(screen.getByText("Enviando…")).toBeInTheDocument();
  });

  it("disables Edit while busy", () => {
    renderDetail({ isBusy: true });
    expect(screen.getByRole("button", { name: "Editar borrador" })).toBeDisabled();
  });
});

describe("ReviewDetail — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderDetail();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
