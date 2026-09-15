"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";

import { useStatementDetail } from "../hooks/use-statements-data";
import { mapStatementDetailState } from "../lib/statements-error";
import { StatementDetail } from "./statement-detail";
import { StatementDownloads } from "./statement-downloads";

export interface StatementDetailStateProps {
  /**
   * The statement to load. Always a concrete id when this component is
   * mounted — the caller (the eventual `/statements/[id]` route, task 6.3)
   * decides *when* to show the detail; this component only ever coordinates
   * one id's loading/error/not-found/success cycle.
   */
  statementId: string;
  /**
   * "Back to list" (R1, R3, task 4.4). A callback rather than a hardcoded
   * `Link` href: the real route/shell is task 6.3's job (D1 — this feature
   * layer does not assume a route exists yet). Because this component keeps
   * no local state of its own beyond the query keyed by
   * `[tenantId, statementId]` (`useStatementDetail`), the caller unmounting
   * this component on `onBack` is what guarantees no other statement's or
   * tenant's data survives the trip back — there is nothing here to reset.
   */
  onBack: () => void;
}

/**
 * Coordinates one statement's detail load (R1, R3, R5, task 4.4): loading,
 * forbidden, not-found and success, handing the loaded `OwnerStatementDetail`
 * to the purely presentational `StatementDetail` on success.
 *
 * **404 never reveals its cause (R3.7, security.md rule 1):** whether the id
 * does not exist or belongs to another tenant, `mapStatementDetailState`
 * already collapses both into the same `not-found` variant — this component
 * renders one generic, translated "not found" state either way and reads
 * nothing else off the error to decide otherwise.
 *
 * **No financial data leaks on `forbidden`/`error`/`not-found`** (R1.2): each
 * of those branches returns before `StatementDetail` (and therefore
 * `OwnerStatementDetail`) is ever referenced.
 */
export function StatementDetailState({ statementId, onBack }: StatementDetailStateProps) {
  const { t } = useTranslation("statements");
  const { t: tStates } = useTranslation("states");
  const query = useStatementDetail(statementId);
  const state = mapStatementDetailState(query);

  const backLink = (
    <Button type="button" variant="ghost" className="tap-target self-start" onClick={onBack}>
      {t("detail.backToList")}
    </Button>
  );

  if (state.kind === "loading") {
    return (
      <div className="flex min-w-0 flex-col gap-3">
        {backLink}
        <LoadingState label={tStates("loading.label")} />
      </div>
    );
  }

  if (state.kind === "forbidden") {
    return (
      <div className="flex min-w-0 flex-col gap-3">
        {backLink}
        <ErrorState title={tStates("error.title")} description={t("detail.error.forbidden")} />
      </div>
    );
  }

  if (state.kind === "not-found") {
    return (
      <div className="flex min-w-0 flex-col gap-3">
        {backLink}
        <EmptyState title={t("detail.notFound.title")} />
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex min-w-0 flex-col gap-3">
        {backLink}
        <ErrorState
          title={tStates("error.title")}
          description={t("detail.error.generic")}
          onRetry={() => void query.refetch()}
          retryLabel={tStates("error.retry")}
        />
      </div>
    );
  }

  // state.kind === "ok"
  //
  // The CSV/PDF export controls (task 5.3) mount here, in the state
  // coordinator, and are handed to `StatementDetail` through its `downloads`
  // slot. Wiring them here keeps `StatementDetail` purely presentational and
  // ignorant of the download hook: only this component ever touches
  // `useStatementDownload` (via `StatementDownloads`), and the controls only
  // exist on the success branch — never leaking exports onto
  // loading/forbidden/not-found/error.
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {backLink}
      <StatementDetail
        statement={state.data}
        downloads={<StatementDownloads statementId={state.data.id} />}
      />
    </div>
  );
}
