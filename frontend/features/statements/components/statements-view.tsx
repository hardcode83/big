"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/lib/auth";

import type { OwnerStatementFilters, OwnerStatementStatus } from "../data";
import { StatementsList } from "./statements-list";

/**
 * `/statements` (design D5, task 3.1). Owns `filters` and `page` as plain
 * local `useState` — a lightweight, view-scoped UI concern, never TanStack
 * Query's job (that stays the only source of statements/property remote
 * state) and never a Zustand store: this view has no cross-tab/cross-route
 * state to share, so a store would be state duplicated for convenience, which
 * design D5 and `steering/frontend.md` both rule out.
 *
 * **Tenant-change reset (security.md rule 1, R1.3):** `filters`/`page` are
 * reset synchronously during render, BEFORE any child reads them, whenever
 * the authenticated tenant id changes — so a stale filter — including any
 * accidental identifier — can never survive into a new tenant's first
 * request. This uses React's "adjusting state during rendering" pattern
 * (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes):
 * an earlier `useEffect`-based reset ran AFTER the render that already passed
 * previous-tenant state to `StatementsList`/`useStatementsList`, so the first
 * query for the new tenant could carry the previous tenant's `propertyId` or
 * `page`. Doing it inline during render makes React discard the in-flight
 * render and re-render with the reset state, so no child ever sees stale
 * values. The `prevTenantId` state guards against resetting on every render
 * with the same tenant.
 *
 * This component never accepts, stores or forwards a `tenant_id`: the only
 * identifier `StatementsList`/`useStatementsList` ever see is the one
 * `useAuth()` already resolved for the authenticated session.
 *
 * `onSelectStatement` (task 6.3) is the bridge from the list to the
 * detail view. The parent (`StatementsPage`) owns the selection state;
 * this component only forwards the id up — it never stores it. Optional
 * with no default, so the existing direct usages (tests, internal mounts)
 * keep compiling unchanged.
 */
export interface StatementsViewProps {
  /**
   * Called when the user activates a row. Receives the contract id of the
   * statement to open. The parent decides whether to mount the detail
   * view (e.g. `StatementsPage` flips its `selectedStatementId`).
   */
  onSelectStatement?: (statementId: string) => void;
}

export function StatementsView({ onSelectStatement }: StatementsViewProps = {}) {
  const { t } = useTranslation("statements");
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;

  const [filters, setFilters] = useState<OwnerStatementFilters>({});
  const [page, setPage] = useState(1);
  const [prevTenantId, setPrevTenantId] = useState<string | null>(tenantId);

  // Adjusting state during rendering: when the authenticated tenant changes,
  // reset filters/page BEFORE any child reads them. The conditional `setState`
  // calls here cause React to discard this render and produce a fresh one
  // with the reset state — no `useEffect`, no intermediate render with stale
  // data, no possibility of the previous tenant's `propertyId` or `page`
  // reaching `useStatementsList`.
  if (prevTenantId !== tenantId) {
    setPrevTenantId(tenantId);
    setFilters({});
    setPage(1);
  }

  // Any filter change moves navigation back to page 1 (R2.3, task 3.2): a
  // filter narrowing the results must not leave the view stranded on a page
  // number the new, smaller result set may not have.
  function updateFilters(patch: Partial<OwnerStatementFilters>) {
    setFilters((prev) => {
      const next: OwnerStatementFilters = { ...prev };
      for (const key of Object.keys(patch) as Array<keyof OwnerStatementFilters>) {
        const value = patch[key];
        if (value === undefined) {
          delete next[key];
        } else {
          (next as Record<string, unknown>)[key] = value;
        }
      }
      return next;
    });
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-3" data-testid="statements-view">
      <h1 className="text-headline-lg font-semibold text-foreground">{t("title")}</h1>
      <StatementsList
        filters={filters}
        page={page}
        onPropertyIdChange={(value) => updateFilters({ propertyId: value })}
        onPeriodStartFromChange={(value) => updateFilters({ periodStartFrom: value })}
        onPeriodStartToChange={(value) => updateFilters({ periodStartTo: value })}
        onStatusChange={(value: OwnerStatementStatus | undefined) =>
          updateFilters({ status: value })
        }
        onPageChange={setPage}
        onSelectStatement={onSelectStatement}
      />
    </div>
  );
}
