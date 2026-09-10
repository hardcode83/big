"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import type { CleaningTask } from "../data";
import type { CancelCleaningTaskInput } from "../hooks/use-cancel-cleaning-task";
import {
  CANCEL_ERROR_TABLE,
  GENERIC_CANCEL_ERROR_KEY,
  keyForStatus,
} from "../lib/manage-error";

const REASON_MAX = 500;

/**
 * Cancelling a live cleaning task from `/cleaning` (R4.1, R4.2, R4.4, R4.5, design D5).
 *
 * Same `Sheet` skeleton as the dashboard's `CancelCleaningDialog` (textarea with
 * `maxLength={REASON_MAX}`, a blank-reason guard, `submittingRef` against a double
 * click) — but its own `cleaning` namespace and its own error mapper
 * (`CANCEL_ERROR_TABLE`/`GENERIC_CANCEL_ERROR_KEY`, R4.5). The two dialogs share no code
 * beyond that shape, on purpose (design D5's accepted duplication — a third consumer of
 * `cancelTask` is the declared trigger to unify them).
 *
 * The mutation is **received by props, never instantiated here** (design D4):
 * `CleaningView` owns the single `useCancelCleaningTask()` instance so its result can
 * also feed the view's one live region. This component only calls `mutation.mutate` and
 * closes itself on success; a failure instead paints its own `role="alert"` right here
 * and leaves the form mounted (design D4's declared exception — see `CleaningView`'s
 * `announcement()` for why the region never repeats this text).
 */
export interface CancelCleaningTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskId: string;
  mutation: UseMutationResult<CleaningTask, Error, CancelCleaningTaskInput>;
}

export function CancelCleaningTaskDialog({
  open,
  onOpenChange,
  taskId,
  mutation,
}: CancelCleaningTaskDialogProps) {
  const { t } = useTranslation("cleaning");
  const closeLabel = t("cancel.title");

  /**
   * Finding 1 (fix round, architect, referent D4): blocks every dismiss path —
   * Escape, an outside click, and the sheet's own `SheetPrimitive.Close` button —
   * while this shared mutation is pending. Radix routes all three through
   * `onOpenChange`, and this component is controlled (`open` is a prop), so simply
   * not forwarding the request keeps the sheet open; there is no separate internal
   * state for Radix to desync from.
   *
   * Without this, dismissing while a request is in flight and reopening for a
   * different row remounts `CancelCleaningTaskDialogBody`, whose mount effect calls
   * `mutation.reset()` on the very same shared mutation object the first (still
   * in-flight) request is bound to — clobbering its pending/settled state and
   * misdirecting its eventual result. `CleaningTaskRow`'s cancel-open button is
   * disabled the same way while pending (mirroring `AssignCleanerControl.isBlocked`),
   * so no other row can open this dialog to begin with — the two guards together
   * make two rows ever contending for it impossible, not just unlikely.
   */
  function handleOpenChange(next: boolean) {
    if (!next && mutation.isPending) {
      return;
    }
    onOpenChange(next);
  }

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent
        side="right"
        closeLabel={closeLabel}
        className="flex flex-col gap-4"
      >
        {open ? (
          <CancelCleaningTaskDialogBody
            key="open"
            taskId={taskId}
            mutation={mutation}
            onClose={() => handleOpenChange(false)}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

interface BodyProps {
  taskId: string;
  mutation: UseMutationResult<CleaningTask, Error, CancelCleaningTaskInput>;
  onClose: () => void;
}

function CancelCleaningTaskDialogBody({ taskId, mutation, onClose }: BodyProps) {
  const { t } = useTranslation("cleaning");
  const [reason, setReason] = useState("");
  const [emptyReasonError, setEmptyReasonError] = useState(false);
  const reasonHintId = useId();
  const reasonErrorId = useId();
  const textareaId = useId();
  const submittingRef = useRef(false);

  /**
   * The mutation instance is shared across every row (design D4) and outlives this
   * body — only the body remounts (`key="open"`) on every open. Without this, opening
   * the dialog for a fresh task right after a previous cancellation's `409` would show
   * that stale error (or a stale success) before the manager has done anything here.
   */
  useEffect(() => {
    mutation.reset();
    // Deliberately once per mount: `mutation` is a fresh object identity on every
    // parent render, and re-running this on that identity change would erase the very
    // state (`isPending`, a just-landed `isError`) it exists to read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    // `mutation.isPending` only flips on the next React commit, so two clicks
    // dispatched in the same frame would both reach `mutate`. This ref closes that
    // window synchronously; `onSettled` reopens it.
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    mutation.mutate(
      { taskId, reason: trimmedReason },
      {
        onSuccess: () => onClose(),
        onError: () => {
          // R4.5: the localized error renders beneath the form; do NOT close the
          // dialog, the manager has to see why and retry or dismiss.
        },
        onSettled: () => {
          submittingRef.current = false;
        },
      },
    );
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle>{t("cancel.title")}</SheetTitle>
        {/* R4.4: a replacement task may appear right after this succeeds — said here so
            a new row is never mistaken for a failure. */}
        <SheetDescription>{t("cancel.warning")}</SheetDescription>
      </SheetHeader>

      <div className="flex flex-col gap-2">
        <label htmlFor={textareaId} className="text-sm font-medium">
          {t("cancel.reason.label")}
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
          placeholder={t("cancel.reason.placeholder")}
          onChange={(event) => {
            setReason(event.target.value);
            if (emptyReasonError && event.target.value.trim().length > 0) {
              setEmptyReasonError(false);
            }
          }}
        />
        <p id={reasonHintId} className="text-xs text-muted-foreground">
          {t("cancel.reason.help")}{" "}
          <span aria-live="polite">
            {t("cancel.reason.charsRemaining", { count: charsRemaining })}
          </span>
        </p>
        {emptyReasonError ? (
          <p
            id={reasonErrorId}
            role="alert"
            className="text-xs text-destructive"
          >
            {t("cancel.reason.empty")}
          </p>
        ) : null}
        {mutation.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {t(
              keyForStatus(
                mutation.error,
                CANCEL_ERROR_TABLE,
                GENERIC_CANCEL_ERROR_KEY,
              ),
            )}
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
          {mutation.isPending ? t("cancel.sending") : t("cancel.confirm")}
        </Button>
      </div>
    </>
  );
}
