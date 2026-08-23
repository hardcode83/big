import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PriceRecommendationStatus } from "../data";
import { DecisionControls } from "./decision-controls";

const useHasPermission = vi.hoisted(() => vi.fn(() => true));
vi.mock("@/lib/auth", () => ({ useHasPermission }));

function renderControls(
  status: PriceRecommendationStatus,
  overrides: { isPending?: boolean; isBusy?: boolean } = {},
) {
  const onConfirm = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <DecisionControls
        recommendationId="rec-1"
        status={status}
        isPending={overrides.isPending ?? false}
        isBusy={overrides.isBusy ?? false}
        onConfirm={onConfirm}
      />
    </I18nProvider>,
  );
  return { ...result, onConfirm };
}

const button = (name: string) => screen.queryByRole("button", { name });

describe("DecisionControls — which moves are offered (R3.1, R3.2)", () => {
  it("offers Approve and Reject on RECOMMENDED", () => {
    renderControls("RECOMMENDED");
    expect(button("Aprobar")).toBeInTheDocument();
    expect(button("Rechazar")).toBeInTheDocument();
    expect(button("Marcar como publicada")).not.toBeInTheDocument();
  });

  it("offers only «Marcar como publicada» on APPROVED (R3.2)", () => {
    // The move that closes Mode 1: without it an approved row is a dead end.
    renderControls("APPROVED");
    expect(button("Marcar como publicada")).toBeInTheDocument();
    expect(button("Aprobar")).not.toBeInTheDocument();
    expect(button("Rechazar")).not.toBeInTheDocument();
  });

  it("offers nothing on DRAFT, APPLIED_EXTERNAL or REJECTED", () => {
    for (const status of [
      "DRAFT",
      "APPLIED_EXTERNAL",
      "REJECTED",
    ] as PriceRecommendationStatus[]) {
      const { container, unmount } = renderControls(status);
      expect(container, `${status} should render nothing`).toBeEmptyDOMElement();
      unmount();
    }
  });
});

describe("DecisionControls — confirmation in two steps (R3.3, design D12)", () => {
  it("does not mutate on the first click", () => {
    const { onConfirm } = renderControls("RECOMMENDED");
    fireEvent.click(button("Aprobar")!);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("asks a question naming the move, not a generic «¿seguro?»", () => {
    renderControls("RECOMMENDED");
    fireEvent.click(button("Rechazar")!);
    expect(screen.getByText("¿Rechazar este precio?")).toBeInTheDocument();
  });

  it("asks a different question per move", () => {
    const approve = renderControls("RECOMMENDED");
    fireEvent.click(button("Aprobar")!);
    expect(screen.getByText("¿Aprobar este precio?")).toBeInTheDocument();
    approve.unmount();

    renderControls("APPROVED");
    fireEvent.click(button("Marcar como publicada")!);
    expect(
      screen.getByText("¿Marcar este precio como publicado?"),
    ).toBeInTheDocument();
  });

  it("mutates only when the confirmation is pressed (R3.3)", () => {
    const { onConfirm } = renderControls("RECOMMENDED");
    fireEvent.click(button("Aprobar")!);
    fireEvent.click(button("Confirmar")!);
    expect(onConfirm).toHaveBeenCalledWith({
      recommendationId: "rec-1",
      status: "APPROVED",
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("sends the status of the move that was confirmed, not the first one", () => {
    const { onConfirm } = renderControls("RECOMMENDED");
    fireEvent.click(button("Rechazar")!);
    fireEvent.click(button("Confirmar")!);
    expect(onConfirm).toHaveBeenCalledWith({
      recommendationId: "rec-1",
      status: "REJECTED",
    });
  });

  it("cancels back to the buttons without mutating", () => {
    const { onConfirm } = renderControls("RECOMMENDED");
    fireEvent.click(button("Aprobar")!);
    fireEvent.click(button("Cancelar")!);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(button("Aprobar")).toBeInTheDocument();
    expect(screen.queryByText("¿Aprobar este precio?")).not.toBeInTheDocument();
  });
});

describe("DecisionControls — while a write is in flight (R3.3, design D8)", () => {
  it("shows the sending text on the row whose decision is flying", () => {
    renderControls("RECOMMENDED", { isPending: true, isBusy: true });
    expect(screen.getByText("Enviando…")).toBeInTheDocument();
    expect(button("Aprobar")).not.toBeInTheDocument();
  });

  it("disables this row's buttons while another row's decision is flying", () => {
    // A second `mutate` would detach the first and swallow its rejection, which
    // R3.6/R3.8 make mandatory to show.
    renderControls("RECOMMENDED", { isPending: false, isBusy: true });
    expect(button("Aprobar")).toBeDisabled();
    expect(button("Rechazar")).toBeDisabled();
  });

  it("disables a confirmation that was already open when another write started", () => {
    // The reachable ordering: the question opens while nothing is in flight,
    // and only then does another row's decision start. Opening it *during*
    // `isBusy` is impossible, because the button that opens it is disabled —
    // so this has to be driven as two renders, not one.
    const onConfirm = vi.fn();
    const { rerender } = render(
      <I18nProvider locale="es">
        <DecisionControls
          recommendationId="rec-1"
          status="RECOMMENDED"
          isPending={false}
          isBusy={false}
          onConfirm={onConfirm}
        />
      </I18nProvider>,
    );

    fireEvent.click(button("Aprobar")!);
    expect(button("Confirmar")).toBeEnabled();

    rerender(
      <I18nProvider locale="es">
        <DecisionControls
          recommendationId="rec-1"
          status="RECOMMENDED"
          isPending={false}
          isBusy
          onConfirm={onConfirm}
        />
      </I18nProvider>,
    );

    expect(button("Confirmar")).toBeDisabled();
    fireEvent.click(button("Confirmar")!);
    expect(onConfirm).not.toHaveBeenCalled();

    // Cancel stays live, so the row is never stuck mid-question waiting for
    // somebody else's request to settle.
    expect(button("Cancelar")).toBeEnabled();
    fireEvent.click(button("Cancelar")!);
    expect(button("Aprobar")).toBeInTheDocument();
  });

  it("cannot open the question at all while another write is in flight", () => {
    const { onConfirm } = renderControls("RECOMMENDED", { isBusy: true });
    fireEvent.click(button("Aprobar")!);
    expect(screen.queryByText("¿Aprobar este precio?")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});

describe("DecisionControls — permission (R7.3, design D17)", () => {
  it("renders nothing without MANAGE_PRICE_RECOMMENDATIONS", () => {
    useHasPermission.mockReturnValueOnce(false);
    const { container } = renderControls("RECOMMENDED");
    expect(container).toBeEmptyDOMElement();
  });

  it("asks for exactly that permission", () => {
    renderControls("RECOMMENDED");
    expect(useHasPermission).toHaveBeenCalledWith(
      "MANAGE_PRICE_RECOMMENDATIONS",
    );
  });
});

describe("DecisionControls — accessibility", () => {
  it("has no violations in either step", async () => {
    const { container } = renderControls("RECOMMENDED");
    expect(await getA11yViolations(container)).toEqual([]);
    fireEvent.click(button("Aprobar")!);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
