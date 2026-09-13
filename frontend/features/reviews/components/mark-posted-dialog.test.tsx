import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { Review, ReviewDraft } from "../data";
import { MarkPostedDialog } from "./mark-posted-dialog";

const REVIEW: Review = {
  id: "rev-1",
  propertyId: "p-1",
  reviewerName: "Jane Doe",
  rating: "4.5",
  content: "Wifi <b>fatal</b>, never again",
  sentiment: "NEGATIVE",
  aiSummary: null,
  recurringIssues: [],
  status: "APPROVED",
  publishedAt: "2026-09-01",
  channel: "AIRBNB",
  language: "en",
};

const DRAFT: ReviewDraft = {
  reviewId: "rev-1",
  draftContent: "Thanks for the feedback, we'll look into the wifi.",
  language: "en",
};

function renderDialog(overrides: {
  open?: boolean;
  review?: Review;
  draft?: ReviewDraft | null;
  isBusy?: boolean;
} = {}) {
  const onOpenChange = vi.fn();
  const onConfirm = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <MarkPostedDialog
        open={overrides.open ?? true}
        onOpenChange={onOpenChange}
        review={overrides.review ?? REVIEW}
        draft={"draft" in overrides ? overrides.draft ?? null : DRAFT}
        isBusy={overrides.isBusy ?? false}
        onConfirm={onConfirm}
      />
    </I18nProvider>,
  );
  return { ...result, onOpenChange, onConfirm };
}

describe("MarkPostedDialog — the preview (D12, R4.1, R4.2)", () => {
  it("shows the guest's text and the approved draft, as text (D11)", () => {
    renderDialog();
    expect(screen.getByText("Wifi <b>fatal</b>, never again")).toBeInTheDocument();
    expect(
      screen.getByText("Thanks for the feedback, we'll look into the wifi."),
    ).toBeInTheDocument();
    // Never parsed as markup — no <b> element created from the guest's text.
    expect(document.querySelector("b")).toBeNull();
  });

  it("falls back to the empty marker when there is no guest content", () => {
    renderDialog({ review: { ...REVIEW, content: null } });
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("omits the draft preview block when there is no draft", () => {
    renderDialog({ draft: null });
    expect(screen.queryByText("Borrador aprobado")).not.toBeInTheDocument();
  });

  it("uses the 'already posted' wording, not 'publish'", () => {
    renderDialog();
    expect(
      screen.getByText(/ya publicaste esta respuesta en el canal correspondiente/),
    ).toBeInTheDocument();
  });
});

describe("MarkPostedDialog — confirmation (R4.2, R4.3)", () => {
  it("does not fire onConfirm when only opened", () => {
    const { onConfirm } = renderDialog();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("fires onConfirm on the confirm button", () => {
    const { onConfirm } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("does not render at all when closed", () => {
    renderDialog({ open: false });
    expect(screen.queryByText("Marcar como publicada")).not.toBeInTheDocument();
  });
});

describe("MarkPostedDialog — busy state (design D9)", () => {
  it("disables confirm and cancel while a write is in flight", () => {
    renderDialog({ isBusy: true });
    expect(screen.getByRole("button", { name: "Confirmar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeDisabled();
  });
});

describe("MarkPostedDialog — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderDialog();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
