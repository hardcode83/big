import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { ReviewStatus } from "../data";
import type { ReviewerRole } from "../lib/review-actions";
import { ReviewActions } from "./review-actions";

function renderActions(
  status: ReviewStatus,
  role: ReviewerRole = "owner",
  overrides: { isPending?: boolean; isBusy?: boolean } = {},
) {
  const onConfirm = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <ReviewActions
        reviewId="rev-1"
        status={status}
        role={role}
        isPending={overrides.isPending ?? false}
        isBusy={overrides.isBusy ?? false}
        onConfirm={onConfirm}
      />
    </I18nProvider>,
  );
  return { ...result, onConfirm };
}

const button = (name: string) => screen.queryByRole("button", { name });

describe("ReviewActions — which moves are offered per status and role (D5, R3.1, R3.2)", () => {
  it("offers Approve, Ignore for the owner on DRAFTED (Edit lives in the detail)", () => {
    renderActions("DRAFTED", "owner");
    expect(button("Aprobar")).toBeInTheDocument();
    expect(button("Ignorar")).toBeInTheDocument();
    // MARK_POSTED and EDIT never render at the row level (D12, R3.3).
    expect(button("Marcar como publicada")).not.toBeInTheDocument();
    expect(button("Editar borrador")).not.toBeInTheDocument();
  });

  it("renders nothing for the manager on DRAFTED (only EDIT is legal, and it is row-excluded)", () => {
    const { container } = renderActions("DRAFTED", "manager");
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing on APPROVED (MARK_POSTED is row-excluded, lives in the detail dialog)", () => {
    const { container } = renderActions("APPROVED", "owner");
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing on the terminal statuses", () => {
    for (const status of ["NEW", "POSTED_MANUALLY", "IGNORED"] as ReviewStatus[]) {
      const { container, unmount } = renderActions(status, "owner");
      expect(container, `${status} should render nothing`).toBeEmptyDOMElement();
      unmount();
    }
  });
});

describe("ReviewActions — confirmation in two steps (R3.3, design D12)", () => {
  it("does not mutate on the first click", () => {
    const { onConfirm } = renderActions("DRAFTED");
    fireEvent.click(button("Aprobar")!);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("asks a question naming the move", () => {
    renderActions("DRAFTED");
    fireEvent.click(button("Ignorar")!);
    expect(screen.getByText("¿Ignorar esta reseña?")).toBeInTheDocument();
  });

  it("mutates only when the confirmation is pressed, with the confirmed action", () => {
    const { onConfirm } = renderActions("DRAFTED");
    fireEvent.click(button("Ignorar")!);
    fireEvent.click(button("Confirmar")!);
    expect(onConfirm).toHaveBeenCalledWith({ reviewId: "rev-1", action: "IGNORE" });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cancels back to the buttons without mutating", () => {
    const { onConfirm } = renderActions("DRAFTED");
    fireEvent.click(button("Aprobar")!);
    fireEvent.click(button("Cancelar")!);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(button("Aprobar")).toBeInTheDocument();
  });
});

describe("ReviewActions — while a write is in flight (design D9)", () => {
  it("shows the sending text on the row whose decision is flying", () => {
    renderActions("DRAFTED", "owner", { isPending: true, isBusy: true });
    expect(screen.getByText("Enviando…")).toBeInTheDocument();
    expect(button("Aprobar")).not.toBeInTheDocument();
  });

  it("disables this row's buttons while another row's decision is flying", () => {
    renderActions("DRAFTED", "owner", { isPending: false, isBusy: true });
    expect(button("Aprobar")).toBeDisabled();
    expect(button("Ignorar")).toBeDisabled();
  });
});

describe("ReviewActions — accessibility", () => {
  it("has no violations in either step", async () => {
    const { container } = renderActions("DRAFTED");
    expect(await getA11yViolations(container)).toEqual([]);
    fireEvent.click(button("Aprobar")!);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
