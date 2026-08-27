"use client";

import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { useCancelCleaningTask } from "@/features/cleaning";

const REASON_MAX = 500;

/**
 * Modal that confirms a cleaning cancellation from the dashboard card
 * (proposal `blocked-transitions-web` R2.2, R3.1, D7).
 *
 * The dialog asks for the **required reason** (`cleaning-stall-blocks-next-stay`
 * R3.1) — bounded to 500 chars client-side so the `422` is impossible — and
 * renders the targeted stall's `trigger` and `blocking_state` as canonical
 * literals above the form. A reason that is empty or whitespace-only is the
 * only client error: the backend refuses it with `422`, so the gate is the
 * same.
 *
 * Submit is disabled while the mutation is in flight (`isPending`), so a
 * double click does not double-cancel; the close button stays enabled so the
 * user can abandon the action without waiting.
 *
 * The dialog body lives behind a `key={open ? "open" : "closed"}` switch so
 * the form is fresh every time the dialog opens — no `useEffect` reset, no
 * cascading render, and the textarea gets focus via the native `autoFocus`
 * attribute (declarative, no synchronous state).
 */
export interface CancelCleaningDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskId: string;
  trigger: string;
  blockingState: string;
}

export function CancelCleaningDialog({
  open,
  onOpenChange,
  taskId,
  trigger,
  blockingState,
}: CancelCleaningDialogProps) {
  const { t } = useTranslation("dashboard");
  const mutation = useCancelCleaningTask();
  const closeLabel = t("card.blocked.cancelCleaning.dialog.title");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        closeLabel={closeLabel}
        className="flex flex-col gap-4"
      >
        {open ? (
          <CancelCleaningDialogBody
            key="open"
            taskId={taskId}
            trigger={trigger}
            blockingState={blockingState}
            mutation={mutation}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

interface BodyProps {
  taskId: string;
  trigger: string;
  blockingState: string;
  mutation: ReturnType<typeof useCancelCleaningTask>;
  onClose: () => void;
}

function CancelCleaningDialogBody({
  taskId,
  trigger,
  blockingState,
  mutation,
  onClose,
}: BodyProps) {
  const { t } = useTranslation("dashboard");
  const [reason, setReason] = useState("");
  const [emptyReasonError, setEmptyReasonError] = useState(false);
  const reasonHintId = useId();
  const reasonErrorId = useId();
  const textareaId = useId();

  const trimmedReason = reason.trim();
  const canSubmit =
    !mutation.isPending &&
    trimmedReason.length > 0 &&
    trimmedReason.length <= REASON_MAX;
  const charsRemaining = REASON_MAX - reason.length;
  const describedBy = [
    reasonHintId,
    emptyReasonError ? reasonErrorId : null,
  ]
    .filter((value): value is string => Boolean(value))
    .join(" ") || undefined;

  function handleSubmit() {
    if (!canSubmit) {
      setEmptyReasonError(trimmedReason.length === 0);
      return;
    }
    mutation.mutate(
      { taskId, reason: trimmedReason },
      {
        onSuccess: () => onClose(),
        onError: () => {
          // R3.3: the localized error renders beneath the form; do NOT close
          // the dialog, the user has to see why and try again or dismiss.
        },
      },
    );
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle>{t("card.blocked.cancelCleaning.dialog.title")}</SheetTitle>
        <SheetDescription>
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            <code className="font-mono text-xs text-foreground">
              {trigger}
            </code>
            <span aria-hidden="true">·</span>
            <code className="font-mono text-xs text-foreground">
              {blockingState}
            </code>
          </span>
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-col gap-2">
        <label htmlFor={textareaId} className="text-sm font-medium">
          {t("card.blocked.cancelCleaning.dialog.reason.label")}
        </label>
        <textarea
          id={textareaId}
          autoFocus
          value={reason}
          maxLength={REASON_MAX}
          rows={4}
          className="min-h-24 w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          aria-describedby={describedBy}
          aria-invalid={emptyReasonError}
          placeholder={t(
            "card.blocked.cancelCleaning.dialog.reason.placeholder",
          )}
          onChange={(event) => {
            setReason(event.target.value);
            if (emptyReasonError && event.target.value.trim().length > 0) {
              setEmptyReasonError(false);
            }
          }}
        />
        <p id={reasonHintId} className="text-xs text-muted-foreground">
          {t("card.blocked.cancelCleaning.dialog.reason.help")}{" "}
          <span aria-live="polite">({charsRemaining})</span>
        </p>
        {emptyReasonError ? (
          <p
            id={reasonErrorId}
            role="alert"
            className="text-xs text-destructive"
          >
            {t("card.blocked.cancelCleaning.dialog.error.empty")}
          </p>
        ) : null}
        {mutation.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {t("card.blocked.cancelCleaning.dialog.error.generic")}
          </p>
        ) : null}
      </div>

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          aria-busy={mutation.isPending}
        >
          {mutation.isPending
            ? t("card.blocked.cancelCleaning.dialog.sending")
            : t("card.blocked.cancelCleaning.dialog.confirm")}
        </Button>
      </div>
    </>
  );
}