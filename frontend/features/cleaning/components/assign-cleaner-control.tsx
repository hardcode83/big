"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { CleaningAssignmentBlocker, CleanerSummary } from "../data";

/** The reason line's copy, one key per cause (R2.4, R3.1). */
const BLOCKED_KEY: Record<CleaningAssignmentBlocker, string> = {
  PROPERTY_STATE: "assign.blocked.propertyState",
  TASK_STATUS: "assign.blocked.taskStatus",
};

/**
 * Picking a cleaner for one task (design D8, R4.1, R4.2).
 *
 * Candidates are the tenant's **active** cleaners, narrowed here on the client from
 * the single unfiltered catalog of design D4 — so an already deactivated cleaner still
 * resolves her name on an old row (R2.2) but is never offered. The backend requires the
 * same thing again and answers `422` if it does not hold; this narrowing is a
 * convenience, not the authority.
 *
 * **The confirm button is not decoration.** R4.1 speaks of *confirming*, and a `<select>`
 * navigated with the arrow keys fires `change` on every option it passes through — an
 * autosubmit would reassign tasks to whoever the manager merely scrolled past.
 *
 * Native `<select>`: there is no `Select` primitive in `components/ui/`, it is what
 * `features/dashboard/components/detail/property-timeline.tsx` already uses, and it
 * brings keyboard support and the mobile wheel for free (R5.3).
 */
export interface AssignCleanerControlProps {
  taskId: string;
  currentCleanerId: string | null;
  cleaners: readonly CleanerSummary[];
  /** This row's own assignment is in flight. */
  isPending: boolean;
  /**
   * Some assignment — this row's or another's — is in flight. The view owns a single
   * mutation, and starting a second one detaches the first, which would swallow its
   * rejection; R4.4/R4.5 make that error mandatory, so the second **confirm** is not
   * reachable until the first settles.
   *
   * It gates the button and NOT the `<select>`, deliberately. Disabling an element
   * that currently has focus makes the browser drop focus to `<body>`, so blocking
   * every row's select would silently strand a keyboard user who was picking in one
   * row when another row's assignment started (R5.3). Choosing is harmless; only
   * sending has to wait.
   */
  isBlocked: boolean;
  /**
   * Why this task cannot be assigned right now, or `null` if nothing known is blocking it
   * (`cleaning-assign-preconditions` R3.1). Arrives computed from the listing — this
   * component derives nothing, which is what keeps "no business logic in components" true
   * (`steering/frontend.md`, design D9).
   *
   * Distinct from `isBlocked` above and the two must not be merged: `isBlocked` means "a
   * mutation is in flight, wait", a transient state of this screen. This means "the server
   * would refuse", a fact about the task and its flat. They disable the same button and say
   * completely different things, and only this one has a reason to show.
   *
   * A courtesy, not a permission: it is computed when the page is read, so it can be stale
   * by the time the manager clicks. The backend refuses again and that refusal is the
   * authority (R3.3) — which is why a stale `null` is safe and a stale non-`null` merely
   * hides a button that would have worked until the next refetch.
   */
  blockedBy: CleaningAssignmentBlocker | null;
  onConfirm: (input: { taskId: string; cleanerId: string }) => void;
}

export function AssignCleanerControl({
  taskId,
  currentCleanerId,
  cleaners,
  isPending,
  isBlocked,
  blockedBy,
  onConfirm,
}: AssignCleanerControlProps) {
  const { t } = useTranslation("cleaning");
  /**
   * Starts **empty**, never preselected with the current cleaner. R4.1 asks the
   * manager to *confirm* a cleaner: a preselected value leaves the button live with
   * zero interaction, so one stray click would PATCH a name nobody picked — and a
   * preselect that went stale while the row was mounted would silently revert
   * somebody else's reassignment. Who is assigned right now is stated above the
   * control by the row itself, so nothing is lost by leaving this blank.
   */
  const [selected, setSelected] = useState<string>("");
  const selectId = `assign-cleaner-${taskId}`;
  const reasonId = `assign-blocked-${taskId}`;
  const candidates = cleaners.filter((cleaner) => cleaner.isActive);
  // Re-sending the value the task already has is not a reassignment; it would just
  // re-fire the backend's notification and audit row.
  const canConfirm =
    blockedBy === null &&
    !isBlocked &&
    selected !== "" &&
    selected !== currentCleanerId;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
      <label className="sr-only" htmlFor={selectId}>
        {t("assign.label")}
      </label>
      <select
        id={selectId}
        className="tap-target min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm"
        value={selected}
        disabled={isPending}
        onChange={(event) => setSelected(event.target.value)}
      >
        <option value="">{t("assign.placeholder")}</option>
        {candidates.map((cleaner) => (
          <option key={cleaner.id} value={cleaner.id}>
            {cleaner.name}
          </option>
        ))}
      </select>
      <Button
        type="button"
        variant="outline"
        disabled={!canConfirm}
        // Points at the reason line only when there is one, so a button that is merely
        // waiting for a selection is not described by a message that is not on screen.
        aria-describedby={blockedBy !== null ? reasonId : undefined}
        onClick={() => onConfirm({ taskId, cleanerId: selected })}
      >
        {isPending ? t("assign.sending") : t("assign.confirm")}
      </Button>
      </div>
      {/*
        Static text and not a `title`: the view is mobile-first, where there is no hover
        (design D8). Rendered only when blocked — an always-present empty node would be
        announced as an empty description by a screen reader.
      */}
      {blockedBy !== null ? (
        <p id={reasonId} className="text-body-base text-muted-foreground">
          {t(BLOCKED_KEY[blockedBy])}
        </p>
      ) : null}
    </div>
  );
}
