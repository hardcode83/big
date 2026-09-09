"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useHasPermission } from "@/lib/auth";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import { severityColorGroup } from "@/features/incidents";

import type { OwnerApprovalListItemDto } from "../data";
import { mapApprovalsError } from "../lib/error-mapping";
import { waitingSince } from "../lib/waiting-since";
import { useApprovals, useApprovalsHistory } from "../hooks/use-approvals";
import { useRespondOwnerApproval } from "../hooks/use-respond-approval";

const BUTTON_CLASS =
  "tap-target rounded-md border bg-background px-3 py-1 text-body-base transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50";

/** Property name + internal code — never a bare UUID (R2.6). */
function propertyLabel(property: OwnerApprovalListItemDto["property"]): string {
  return `${property.name} (${property.internalCode})`;
}

/**
 * One row's "request" cell: the originating incident, translated, or the
 * `OTHER` note when there is none (D11). Never a raw UUID.
 */
function RequestCell({
  row,
  t,
}: {
  row: OwnerApprovalListItemDto;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  if (row.relatedType === "OTHER" || !row.incident) {
    return <span>{t("approvals:queue.otherNote")}</span>;
  }
  const incident = row.incident;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-foreground">{incident.title}</span>
      <div className="flex items-center gap-2">
        <span
          className={TONE_BADGE_CLASS[severityColorGroup(incident.severity)]}
        >
          {t(`incidents:severity.${incident.severity}`)}
        </span>
        <span className="text-body-medium text-muted-foreground">
          {t(`incidents:category.${incident.category}`)}
        </span>
      </div>
    </div>
  );
}

/**
 * The `/approvals` screen (proposal R2, R3; design D9-D11). Two independent
 * queries — `useApprovals()` for the pending queue, `useApprovalsHistory()`
 * for the last five answered — rendered with the same loading/empty/error/
 * retry shapes `incidents-view.tsx` uses (R2.4), never inventing new ones.
 *
 * Approve/reject controls (R3.1-R3.6) are gated behind
 * `useHasPermission("RESPOND_OWNER_APPROVALS")` — a UX hint only, the backend
 * remains the authority (`steering/security.md` rule 2) — and are never
 * offered on an `OTHER` row (D11), which gets only the translated note.
 */
export function ApprovalsView() {
  const { t } = useTranslation(["approvals", "states", "incidents"]);
  const queueQuery = useApprovals();
  const history = useApprovalsHistory();
  const canRespond = useHasPermission("RESPOND_OWNER_APPROVALS");
  const respondMutation = useRespondOwnerApproval();
  const [notesByRow, setNotesByRow] = useState<Record<string, string>>({});

  const queueState = mapApprovalsError(queueQuery);

  function handleRespond(row: OwnerApprovalListItemDto, status: "APPROVED" | "REJECTED") {
    const typed = notesByRow[row.id];
    respondMutation.mutate({
      approvalId: row.id,
      status,
      responseNotes: typed === undefined || typed === "" ? undefined : typed,
    });
  }

  if (queueState.kind === "loading") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("states:loading.label", { ns: "states" })}
      </p>
    );
  }
  if (queueState.kind === "forbidden") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("approvals:fields.forbidden")}
      </p>
    );
  }
  if (queueState.kind === "validation") {
    return (
      <p className="p-4 text-body-base text-muted-foreground">
        {t("approvals:fields.validation")}
      </p>
    );
  }
  if (
    queueState.kind === "not-found" ||
    queueState.kind === "error" ||
    queueState.kind === "already-answered"
  ) {
    // `already-answered` cannot come back from `GET /owner-approvals` — it is
    // `mapApprovalsError`'s 409 mapping for the respond *mutation*, and this
    // is the read query's own result. Folded into the generic error state
    // rather than left unhandled, purely so `queueState` narrows to `"ok"`
    // below without a type assertion; there is nothing for the queue to do
    // with a kind it can never actually receive.
    return (
      <div className="flex flex-col gap-2 p-4">
        <p className="text-body-lg font-semibold text-foreground">
          {t("states:error.title", { ns: "states" })}
        </p>
        <p className="text-body-base text-muted-foreground">
          {t("states:error.description", { ns: "states" })}
        </p>
        <button
          type="button"
          className={`${BUTTON_CLASS} self-start`}
          onClick={() => {
            void queueQuery.refetch();
          }}
        >
          {t("states:error.retry", { ns: "states" })}
        </button>
      </div>
    );
  }

  // queueState.kind === "ok"
  const items = queueState.data.items;

  return (
    <section aria-labelledby="approvals-heading" className="flex flex-col gap-6 p-4">
      <h1 id="approvals-heading" className="text-xl font-semibold text-foreground">
        {t("approvals:queue.title")}
      </h1>

      {items.length === 0 ? (
        <>
          <p className="text-body-lg font-semibold text-foreground">
            {t("states:empty.title", { ns: "states" })}
          </p>
          <p className="text-body-base text-muted-foreground">
            {t("states:empty.description", { ns: "states" })}
          </p>
        </>
      ) : (
        <div className="bg-surface border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border">
                  <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                    {t("approvals:queue.columns.property")}
                  </th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                    {t("approvals:queue.columns.request")}
                  </th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                    {t("approvals:queue.columns.amount")}
                  </th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                    {t("approvals:queue.columns.waiting")}
                  </th>
                  {canRespond ? (
                    <th scope="col" className="whitespace-nowrap px-4 py-3 text-body-medium text-muted-foreground">
                      {t("approvals:queue.columns.actions")}
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const since = waitingSince(row.requestedAt);
                  const offersDecision = canRespond && row.relatedType !== "OTHER";
                  const isSubmittingThisRow =
                    respondMutation.isPending &&
                    respondMutation.variables?.approvalId === row.id;
                  const rowErrorState =
                    respondMutation.variables?.approvalId === row.id
                      ? mapApprovalsError(respondMutation)
                      : null;

                  return (
                    <tr key={row.id} className="border-b border-border last:border-b-0 align-top">
                      <td className="px-4 py-3 text-body-base text-foreground">
                        {propertyLabel(row.property)}
                      </td>
                      <td className="px-4 py-3 text-body-base">
                        <RequestCell row={row} t={t} />
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap font-mono text-data-mono text-foreground">
                        {row.amount} {row.currency}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-body-base text-muted-foreground">
                        {since
                          ? t(`approvals:queue.waitingSince.${since.unit}`, {
                              count: since.count,
                            })
                          : row.requestedAt}
                      </td>
                      {canRespond ? (
                        <td className="px-4 py-3">
                          {offersDecision ? (
                            <div className="flex flex-col gap-2">
                              <label className="flex flex-col gap-1 text-body-medium text-muted-foreground">
                                {t("approvals:queue.notesLabel")}
                                <input
                                  type="text"
                                  className="rounded-md border bg-background px-2 py-1 text-body-base text-foreground"
                                  placeholder={t("approvals:queue.notesPlaceholder")}
                                  value={notesByRow[row.id] ?? ""}
                                  onChange={(event) =>
                                    setNotesByRow((prev) => ({
                                      ...prev,
                                      [row.id]: event.target.value,
                                    }))
                                  }
                                  disabled={isSubmittingThisRow}
                                />
                              </label>
                              <div className="flex flex-wrap items-center gap-2">
                                <button
                                  type="button"
                                  className={BUTTON_CLASS}
                                  disabled={isSubmittingThisRow}
                                  onClick={() => handleRespond(row, "APPROVED")}
                                >
                                  {t("approvals:queue.approve")}
                                </button>
                                <button
                                  type="button"
                                  className={BUTTON_CLASS}
                                  disabled={isSubmittingThisRow}
                                  onClick={() => handleRespond(row, "REJECTED")}
                                >
                                  {t("approvals:queue.reject")}
                                </button>
                              </div>
                              <p className="text-body-medium text-state-warning-text">
                                {t("approvals:queue.rejectWarning")}
                              </p>
                              {rowErrorState?.kind === "already-answered" ? (
                                <p role="alert" className="text-body-medium text-state-error-text">
                                  {t("approvals:fields.alreadyAnswered")}
                                </p>
                              ) : null}
                              {rowErrorState?.kind === "forbidden" ? (
                                <p role="alert" className="text-body-medium text-state-error-text">
                                  {t("approvals:fields.forbidden")}
                                </p>
                              ) : null}
                              {rowErrorState?.kind === "validation" ? (
                                <p role="alert" className="text-body-medium text-state-error-text">
                                  {t("approvals:fields.validation")}
                                </p>
                              ) : null}
                              {rowErrorState?.kind === "error" ? (
                                <p role="alert" className="text-body-medium text-state-error-text">
                                  {t("states:error.description", { ns: "states" })}
                                </p>
                              ) : null}
                            </div>
                          ) : (
                            // D11: the note already renders once, in the request
                            // column (`RequestCell`) — this cell stays empty
                            // rather than repeating it, since an `OTHER` row is
                            // never offered a decision here.
                            <span className="text-muted-foreground" aria-hidden="true">
                              —
                            </span>
                          )}
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <h2 className="text-body-lg font-semibold text-foreground">
        {t("approvals:history.title")}
      </h2>
      {history.isPending ? (
        <p className="text-body-base text-muted-foreground">
          {t("states:loading.label", { ns: "states" })}
        </p>
      ) : history.items.length === 0 ? (
        <p className="text-body-base text-muted-foreground">
          {t("approvals:history.empty")}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {history.items.map((row) => (
            <li
              key={row.id}
              className="flex flex-col gap-1 rounded-lg border border-border bg-surface p-3"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-body-base text-foreground">
                  {propertyLabel(row.property)}
                </span>
                <span
                  className={
                    row.status === "APPROVED"
                      ? TONE_BADGE_CLASS.green
                      : TONE_BADGE_CLASS.red
                  }
                >
                  {t(`approvals:status.${row.status}`)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 text-body-medium text-muted-foreground">
                <span>
                  {row.relatedType === "OTHER" || !row.incident
                    ? t("approvals:relatedType.OTHER")
                    : row.incident.title}
                </span>
                <span className="font-mono text-data-mono">
                  {row.amount} {row.currency}
                </span>
              </div>
              {row.respondedAt ? (
                <span className="text-body-medium text-muted-foreground">
                  {t("approvals:history.respondedOn", {
                    date: row.respondedAt.slice(0, 10),
                  })}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
