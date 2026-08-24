"use client";

import { useTranslation } from "react-i18next";

import type { BlockedTransitionSummary } from "../data";
import { formatDateTime } from "../../lib/format";

/**
 * Read-path section that surfaces blocked transitions on the property card
 * (proposal `blocked-transitions-web` R1.2, R1.3, R4.2).
 *
 * The component is render-only — no business logic, no derivation, no
 * translation of the canonical literals. The two fields the backend
 * delivers as canonicals (`trigger`, `blocking_state`) are painted as
 * such in a monospaced `<code>`, and `due_since` is formatted with `Intl`
 * in the user's locale. Adding a "human label" mapping here would be the
 * parallel catalogue R4.3 explicitly forbids.
 *
 * The section renders nothing when `stalls.length === 0`: the card stays
 * untouched. The heading id derives from the property so multiple cards on
 * the same `/dashboard` view keep distinct labelled regions.
 */

export function BlockedTransitionsSection({
  stalls,
  headingId,
}: {
  stalls: BlockedTransitionSummary[];
  headingId: string;
}) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;

  if (stalls.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby={headingId} className="min-w-0">
      <h4 id={headingId} className="text-sm font-semibold text-foreground">
        {t("card.blocked.title")}
      </h4>
      <ul className="mt-2 flex min-w-0 flex-col gap-1.5 text-sm">
        {stalls.map((stall) => (
          <li
            key={`${stall.property_id}-${stall.reservation_id}-${stall.trigger}`}
            className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1 text-muted-foreground"
          >
            <code className="font-mono text-xs text-foreground">
              {stall.trigger}
            </code>
            <span aria-hidden="true">·</span>
            <code className="font-mono text-xs text-foreground">
              {stall.blocking_state}
            </code>
            <span aria-hidden="true">·</span>
            <span className="text-xs">
              {formatDateTime(stall.due_since, locale)}
            </span>
          </li>
        ))}
      </ul>
      {/*
        One row, body size, no new variants. Names the 30-day window the user is
        about to mistake for "the system forgot this" (R5.1, blocked-transitions-web).
      */}
      <p className="mt-2 text-xs text-muted-foreground">
        {t("card.blocked.window")}
      </p>
    </section>
  );
}