"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useHasPermission } from "@/lib/auth";

import type { BlockedTransitionSummary } from "../data";
import { actionMapFor } from "../lib/action-map";
import { formatDateTime } from "../../lib/format";

import { CancelCleaningDialog } from "./cancel-cleaning-dialog";
import { ResolveIncidentDialog } from "./resolve-incident-dialog";

/**
 * Read-path section that surfaces blocked transitions on the property card
 * (proposal `blocked-transitions-web` R1.2, R1.3, R4.2).
 *
 * The component is render-only for the data — no business logic, no
 * derivation, no translation of the canonical literals. The two fields the
 * backend delivers as canonicals (`trigger`, `blocking_state`) are painted as
 * such in a monospaced `<code>`, and `due_since` is formatted with `Intl` in
 * the user's locale. Adding a "human label" mapping here would be the
 * parallel catalogue R4.3 explicitly forbids.
 *
 * The actions row is what 5.x wires up: the **matrix** (`action-map.ts`) is
 * the source of truth for "what can a row offer"; the **permissions hook** is
 * the source of truth for "what can the role do". The two are joined here
 * (R2.4 — never paint a button that would `403`), and a row that resolves to
 * `null` shows no button at all (D6).
 *
 * The section renders nothing when `stalls.length === 0` **and** the stalls
 * query succeeded: the card stays untouched. When the query failed, the
 * section renders its localized error instead of disappearing — R5.3 forbids
 * hiding the card behind a global error, and an empty card is
 * indistinguishable from «this property has no blockers», which is the exact
 * silence this whole change exists to end.
 *
 * The heading id derives from the property so multiple cards on the same
 * `/dashboard` view keep distinct labelled regions.
 */

interface CancelDialogState {
  taskId: string;
  trigger: string;
  blockingState: string;
}

interface ResolveDialogState {
  incidentId: string;
  trigger: string;
  blockingState: string;
}

export function BlockedTransitionsSection({
  stalls,
  headingId,
  hasError = false,
}: {
  stalls: BlockedTransitionSummary[];
  headingId: string;
  /** `true` when the dashboard's stalls query failed (R5.3). */
  hasError?: boolean;
}) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const canCancelCleaning = useHasPermission("MANAGE_CLEANING_TASKS");
  const canResolveIncident = useHasPermission("EXECUTE_INCIDENTS");

  const [cancelFor, setCancelFor] = useState<CancelDialogState | null>(null);
  const [resolveFor, setResolveFor] = useState<ResolveDialogState | null>(null);

  if (stalls.length === 0 && !hasError) {
    return null;
  }

  if (hasError) {
    return (
      <section aria-labelledby={headingId} className="min-w-0">
        <h4 id={headingId} className="text-body-base text-muted-foreground">
          {t("card.blocked.title")}
        </h4>
        <p role="alert" className="mt-2 text-body-base text-destructive">
          {t("card.blocked.error.fetch")}
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby={headingId} className="min-w-0">
      <h4 id={headingId} className="text-body-base text-muted-foreground">
        {t("card.blocked.title")}
      </h4>
      <ul className="mt-2 flex min-w-0 flex-col gap-1.5 text-sm">
        {stalls.map((stall) => {
          const kind = actionMapFor(stall.trigger, stall.blocking_state);
          const showCancel =
            kind === "cancel-cleaning" && canCancelCleaning && Boolean(stall.cleaning_task_id);
          const showResolve =
            kind === "resolve-incident" && canResolveIncident && Boolean(stall.incident_id);
          return (
            <li
              key={`${stall.property_id}-${stall.reservation_id}-${stall.trigger}`}
              className="flex min-w-0 flex-col gap-1 text-muted-foreground"
            >
              {/*
                Two rows rather than one wrapping row. A single `flex-wrap` row
                left the separator stranded at the end of a line whenever the
                date wrapped away from the literals — «CHECKIN_TIME_REACHED ·
                MAINTENANCE_REQUIRED ·» with nothing after it. Splitting the
                literals from the date means a wrap can only ever happen
                *between* the rows, where no separator lives.
              */}
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <code className="font-mono text-data-mono text-foreground">
                  {stall.trigger}
                </code>
                {/*
                  The separator travels with the literal it precedes, in a
                  non-wrapping box, so it leads a wrapped line instead of
                  trailing one.
                */}
                <span className="inline-flex items-baseline gap-x-2">
                  <span aria-hidden="true">·</span>
                  <code className="font-mono text-data-mono text-foreground">
                    {stall.blocking_state}
                  </code>
                </span>
              </div>
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-body-base">
                  {formatDateTime(stall.due_since, locale)}
                </span>
              {showCancel ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() =>
                    setCancelFor({
                      taskId: stall.cleaning_task_id ?? "",
                      trigger: stall.trigger,
                      blockingState: stall.blocking_state,
                    })
                  }
                >
                  {t("card.blocked.cancelCleaning.label")}
                </Button>
              ) : null}
              {showResolve ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() =>
                    setResolveFor({
                      incidentId: stall.incident_id ?? "",
                      trigger: stall.trigger,
                      blockingState: stall.blocking_state,
                    })
                  }
                >
                  {t("card.blocked.resolveIncident.label")}
                </Button>
              ) : null}
              </div>
            </li>
          );
        })}
      </ul>
      {/*
        One row, body size, no new variants. Names the 30-day window the user is
        about to mistake for "the system forgot this" (R5.1, blocked-transitions-web).
      */}
      <p className="mt-2 text-body-base text-muted-foreground">
        {t("card.blocked.window")}
      </p>

      {cancelFor ? (
        <CancelCleaningDialog
          open
          onOpenChange={(open) => {
            if (!open) {
              setCancelFor(null);
            }
          }}
          taskId={cancelFor.taskId}
          trigger={cancelFor.trigger}
          blockingState={cancelFor.blockingState}
        />
      ) : null}
      {resolveFor ? (
        <ResolveIncidentDialog
          open
          onOpenChange={(open) => {
            if (!open) {
              setResolveFor(null);
            }
          }}
          incidentId={resolveFor.incidentId}
          trigger={resolveFor.trigger}
          blockingState={resolveFor.blockingState}
        />
      ) : null}
    </section>
  );
}