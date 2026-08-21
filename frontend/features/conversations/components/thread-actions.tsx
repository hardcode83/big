"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

import type { ConversationDetail } from "../data/dto";
import { useEscalate, useResolve } from "../hooks/use-conversation-actions";
import { errorMessageKey } from "../lib/errors";
import { escalateGate, resolveGate } from "../lib/transitions";

const ESCALATE_REASON_ID = "thread-action-escalate-reason";
const RESOLVE_REASON_ID = "thread-action-resolve-reason";

/**
 * Escalate and resolve (R5.1–R5.4).
 *
 * The gates come from `lib/transitions.ts`, which reads **both** state axes: a
 * `RESOLVED` conversation whose escalation axis is `NONE` is not escalatable, and
 * offering it would be promising a 409 (design D10).
 *
 * An action that does not fit is rendered `disabled` with `aria-describedby`
 * pointing at the localized reason, never hidden (D11): a button that disappears
 * does not tell the manager why. Hiding is what the *role* gate does, which is a
 * different question (D12).
 *
 * Resolving asks for confirmation (R5.4). A 409 shows the localized error and the
 * mutation hook refreshes the real state, so the UI never keeps showing a result
 * that did not happen (D18).
 */
export function ThreadActions({
  conversation,
}: {
  conversation: ConversationDetail;
}) {
  const { t } = useTranslation("conversations");
  const escalate = useEscalate(conversation.id);
  const resolve = useResolve(conversation.id);

  const escalateAllowed = escalateGate(conversation);
  const resolveAllowed = resolveGate(conversation);

  return (
    <section
      aria-label={t("actions.legend")}
      className="flex flex-col gap-2 border-t p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!escalateAllowed.enabled || escalate.isPending}
          aria-describedby={
            escalateAllowed.enabled ? undefined : ESCALATE_REASON_ID
          }
          onClick={() => escalate.mutate()}
        >
          {t("actions.escalate")}
        </Button>

        <ConfirmDialog
          trigger={
            <Button
              type="button"
              size="sm"
              disabled={!resolveAllowed.enabled || resolve.isPending}
              aria-describedby={
                resolveAllowed.enabled ? undefined : RESOLVE_REASON_ID
              }
            >
              {t("actions.resolve")}
            </Button>
          }
          title={t("actions.confirmResolve.title")}
          description={t("actions.confirmResolve.description")}
          confirmLabel={t("actions.confirmResolve.confirm")}
          cancelLabel={t("actions.confirmResolve.cancel")}
          onConfirm={() => resolve.mutate()}
        />
      </div>

      {escalateAllowed.enabled ? null : (
        <p id={ESCALATE_REASON_ID} className="text-xs text-muted-foreground">
          {t(escalateAllowed.reasonKey)}
        </p>
      )}
      {resolveAllowed.enabled ? null : (
        <p id={RESOLVE_REASON_ID} className="text-xs text-muted-foreground">
          {t(resolveAllowed.reasonKey)}
        </p>
      )}

      {escalate.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {t(errorMessageKey(escalate.error))}
        </p>
      ) : null}
      {resolve.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {t(errorMessageKey(resolve.error))}
        </p>
      ) : null}
    </section>
  );
}
