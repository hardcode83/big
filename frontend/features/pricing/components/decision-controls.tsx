"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useHasPermission } from "@/lib/auth";

import type { DecisionStatus, PriceRecommendationStatus } from "../data";
import { legalMoves } from "../lib/decision-moves";

/**
 * The decision buttons for one row, with confirmation in two steps **inside the
 * row** (design D12, R3.1–R3.3).
 *
 * There is no `AlertDialog` in the tree, and `window.confirm` is out: it blocks
 * the thread, does not go through i18next like the rest of the UI, and would have
 * to be stubbed in every test. The in-row form is what `assign-cleaner-control.tsx`
 * already does (choose, then confirm) and it works on mobile with no focus trap
 * to build.
 *
 * **The question names the move.** «¿Aprobar este precio?» rather than a generic
 * «¿seguro?», so the user confirms *what* she is doing — which is also why the
 * catalog carries one question per move.
 *
 * Which buttons appear comes from `legalMoves`, an affordance map and not
 * authority: the backend validates and answers `409`, and this screen has copy of
 * its own for that. A row with no legal moves renders nothing at all.
 *
 * Hidden entirely without `MANAGE_PRICE_RECOMMENDATIONS` (R7.3, design D17) — the
 * frontend hides, the backend decides.
 */
export interface DecisionControlsProps {
  recommendationId: string;
  status: PriceRecommendationStatus;
  /** This row's own decision is in flight. */
  isPending: boolean;
  /**
   * Some decision — this row's or another's — is in flight. The view owns a
   * single mutation, and starting a second one detaches the first and swallows
   * its rejection, which R3.6/R3.8 make mandatory to show (design D8).
   */
  isBusy: boolean;
  onConfirm: (input: {
    recommendationId: string;
    status: DecisionStatus;
  }) => void;
}

/** The i18n key of each move's button label. */
const LABEL_KEY: Record<DecisionStatus, string> = {
  APPROVED: "decide.approve",
  REJECTED: "decide.reject",
  APPLIED_EXTERNAL: "decide.markPublished",
};

export function DecisionControls({
  recommendationId,
  status,
  isPending,
  isBusy,
  onConfirm,
}: DecisionControlsProps) {
  const { t } = useTranslation("pricing");
  const canDecide = useHasPermission("MANAGE_PRICE_RECOMMENDATIONS");
  /** Local to this row: two rows can never be mid-confirmation of each other. */
  const [pendingMove, setPendingMove] = useState<DecisionStatus | null>(null);

  const moves = legalMoves(status);
  if (!canDecide || moves.length === 0) {
    return null;
  }

  if (isPending) {
    return (
      <p className="text-body-base text-muted-foreground">{t("decide.sending")}</p>
    );
  }

  if (pendingMove !== null) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-body-base text-foreground">
          {t(`decide.confirmQuestion.${pendingMove}`)}
        </span>
        <Button
          type="button"
          variant="outline"
          disabled={isBusy}
          onClick={() => {
            // The confirmation is what fires the mutation (R3.3).
            onConfirm({ recommendationId, status: pendingMove });
            setPendingMove(null);
          }}
        >
          {t("decide.confirm")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => setPendingMove(null)}
        >
          {t("decide.cancel")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {moves.map((move) => (
        <Button
          key={move}
          type="button"
          variant="outline"
          disabled={isBusy}
          onClick={() => setPendingMove(move)}
        >
          {t(LABEL_KEY[move])}
        </Button>
      ))}
    </div>
  );
}
