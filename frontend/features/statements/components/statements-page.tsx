"use client";

import { useState } from "react";

import { StatementDetailState } from "./statement-detail-state";
import { StatementsView } from "./statements-view";

/**
 * Entry view of the `/statements` route (task 6.3, design D5-D6).
 *
 * The route is a single screen — there is no `/statements/[id]` segment — so
 * the selection between list and detail lives in local React state owned by
 * this orchestrator, not in the URL. The workspace `layout.tsx` already
 * gates the route behind the workspace shell + auth guard; this component
 * does not add another guard or permission check (R1, D6 — the backend is
 * the authority, the frontend only orchestrates the view).
 *
 * The two branches are:
 *
 * - `selectedStatementId === null` — the listing (`StatementsView`), which
 *   owns its own `filters`/`page` and never accepts, stores or forwards a
 *   `tenant_id`. Selecting a row in the list moves into the detail branch.
 * - `selectedStatementId !== null` — `StatementDetailState` mounts the
 *   detail for that id and renders its own loading/error/not-found/success
 *   cycle. The "back to list" control calls `onSelect(null)`, which unmounts
 *   the detail entirely — no statement's or tenant's data is ever retained
 *   between visits because the detail query is keyed by
 *   `[tenantId, statementId]` and is destroyed with the component.
 *
 * **No `tenant_id` is read or forwarded here either** — the route's tenant
 * is the authenticated session's tenant, and both child branches resolve it
 * through `useAuth()` exactly the way they did before this orchestrator
 * existed. R1.3 is preserved by construction.
 */
export function StatementsPage() {
  const [selectedStatementId, setSelectedStatementId] = useState<string | null>(null);

  if (selectedStatementId === null) {
    return (
      <StatementsView
        onSelectStatement={(statementId) => setSelectedStatementId(statementId)}
      />
    );
  }

  return (
    <StatementDetailState
      statementId={selectedStatementId}
      onBack={() => setSelectedStatementId(null)}
    />
  );
}
