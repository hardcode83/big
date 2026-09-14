"use client";

import { useEffect, useRef, useState } from "react";
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
 * reset to their initial values whenever the authenticated tenant id changes,
 * so a stale filter — including any accidental identifier — never survives
 * into a new tenant's request. The `tenantIdRef` guard is what makes this a
 * reset-on-*change* rather than a reset-on-every-render: the first render
 * (ref seeded to the initial tenant) must NOT clear filters a caller passed
 * via props/tests before the first paint.
 *
 * This component never accepts, stores or forwards a `tenant_id`: the only
 * identifier `StatementsList`/`useStatementsList` ever see is the one
 * `useAuth()` already resolved for the authenticated session.
 */
export function StatementsView() {
  const { t } = useTranslation("statements");
  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? null;

  const [filters, setFilters] = useState<OwnerStatementFilters>({});
  const [page, setPage] = useState(1);
  const tenantIdRef = useRef(tenantId);

  useEffect(() => {
    if (tenantIdRef.current !== tenantId) {
      tenantIdRef.current = tenantId;
      setFilters({});
      setPage(1);
    }
  }, [tenantId]);

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
      />
    </div>
  );
}
