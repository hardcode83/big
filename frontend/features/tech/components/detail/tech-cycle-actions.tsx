"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  conflictReason,
  useIncidentCycleAction,
  useResolveIncident,
  type IncidentCycleAction,
  type IncidentDetailDto,
} from "@/features/incidents";

import { techActions, techNoActionReason } from "../../lib/tech-actions";
import { TechEtaField, etaToInstant } from "./tech-eta-field";
import { TechResolveForm } from "./tech-resolve-form";

const ETA_ACTIONS: readonly IncidentCycleAction[] = ["accept", "en-route"];

/**
 * The action bar at the end of the flow (R3.1, R3.2, design D6, D15).
 *
 * It offers exactly what `techActions` returns for the current status. In
 * `AWAITING_OWNER_APPROVAL`, `RESOLVED` and `CANCELLED` it offers nothing and
 * says why. On a `409` it shows the reason `conflictReason` derives from the
 * **refreshed** status — the three refusals share `code: "CONFLICT"` and differ
 * only in an English message, which R6.2 forbids rendering — and it does not
 * retry.
 */
export function TechCycleActions({ incident }: { incident: IncidentDetailDto }) {
  const { t } = useTranslation("tech");
  const router = useRouter();
  const [eta, setEta] = useState("");
  // Where a successful `reject` goes is this screen's business, not the shared
  // data layer's (R3.5, design D1).
  const cycle = useIncidentCycleAction({
    onRejected: () => router.replace("/tech"),
  });
  const resolve = useResolveIncident();

  const actions = techActions(incident.status);
  const cycleActions = actions.filter(
    (action): action is IncidentCycleAction => action !== "resolve",
  );
  const offersResolve = actions.includes("resolve");
  const offersEta = cycleActions.some((action) => ETA_ACTIONS.includes(action));

  /**
   * `conflictReason` reads the status the query already refreshed — the
   * mutation invalidates in `onSettled`, so by the time this renders the
   * `incident` prop is the one the server just confirmed.
   */
  const messageFor = (
    error: Error | null,
    carriedEta = false,
  ): string | undefined => {
    if (!error) return undefined;
    if (error instanceof ApiError && error.status === 409) {
      return t(`actions.conflict.${conflictReason(incident.status)}`);
    }
    // A 422 is only *about the ETA* when an ETA was actually sent. `wait-parts`
    // and `resume` carry no body at all, so answering one of those with "the
    // server did not accept that time" names a field the technician never
    // filled in (R3.4 governs the ETA case, not every 422).
    if (error instanceof ApiError && error.status === 422 && carriedEta) {
      return t("eta.invalid");
    }
    return t("actions.error");
  };

  // `cycle.variables` is the input of the mutation the error belongs to, so
  // this asks whether *that* request carried an ETA, not whether the field
  // happens to hold text now.
  const cycleCarriedEta = cycle.variables?.etaAt !== undefined;
  const cycleError = messageFor(cycle.error, cycleCarriedEta);
  const etaWas422 =
    cycle.error instanceof ApiError &&
    cycle.error.status === 422 &&
    cycleCarriedEta;
  const resolveIs422 =
    resolve.error instanceof ApiError && resolve.error.status === 422;

  // The refusal is reported even when the refreshed status leaves no action to
  // offer — which is precisely what a 409 for `closed` or `awaiting-owner`
  // produces. Returning early here would swallow the message R3.7 requires.
  if (actions.length === 0) {
    return (
      <section className="flex flex-col gap-2 rounded-lg border bg-surface p-4">
        {cycleError ? (
          <p role="alert" className="text-sm text-state-error-text">
            {cycleError}
          </p>
        ) : null}
        <p className="text-sm text-muted-foreground">
          {t(`actions.none.${techNoActionReason(incident.status)}`)}
        </p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border bg-surface p-4">
      <h2 className="text-base font-semibold text-foreground">
        {t("actions.title")}
      </h2>

      {offersEta ? (
        <TechEtaField
          value={eta}
          onChange={setEta}
          disabled={cycle.isPending}
          error={etaWas422 ? t("eta.invalid") : undefined}
        />
      ) : null}

      {cycleActions.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {cycleActions.map((action) => (
            <Button
              key={action}
              type="button"
              className="min-h-11"
              variant={action === "reject" ? "outline" : "default"}
              disabled={cycle.isPending}
              onClick={() =>
                cycle.mutate({
                  incidentId: incident.id,
                  action,
                  ...(ETA_ACTIONS.includes(action)
                    ? { etaAt: etaToInstant(eta) }
                    : {}),
                })
              }
            >
              {t(`actions.${action}`)}
            </Button>
          ))}
        </div>
      ) : null}

      {cycleError && !etaWas422 ? (
        <p role="alert" className="text-sm text-state-error-text">
          {cycleError}
        </p>
      ) : null}

      {offersResolve ? (
        <TechResolveForm
          isPending={resolve.isPending}
          serverError={
            resolve.error
              ? resolveIs422
                ? t("resolve.errors.server")
                : messageFor(resolve.error)
              : undefined
          }
          onSubmit={(input) =>
            resolve.mutate({ incidentId: incident.id, ...input })
          }
        />
      ) : null}
    </section>
  );
}
