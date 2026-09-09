"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type {
  CleaningTaskStatus,
  CleaningValidationStatus,
  CleaningValidationVerdict,
} from "../data";

/**
 * Recording a manager's verdict on a finished cleaning (design D6, R3.1, R3.4, R3.6).
 *
 * Two explicit `<button>`s, never a `<select>` + confirm: the danger that justified that
 * pattern in `AssignCleanerControl` — an arrow-key traversal firing `change` on every
 * option — does not exist here, there is nothing to navigate. What the two controls share
 * is the same courtesy of not re-sending a no-op: **the button whose verdict is already the
 * task's current one is disabled**, for the same reason `AssignCleanerControl` will not
 * reconfirm the cleaner already assigned.
 *
 * The control does **not** disappear once a verdict exists (amendment R3.1): a `FAILED`
 * pressed by mistake notifies the assigned cleaner, and the only product-side remedy is to
 * be able to correct it from the same screen. `record_manual_validation` only requires
 * `COMPLETED` and never inspects the previous verdict, so revalidating opens no new route.
 */
export interface ValidateCleaningControlProps {
  taskId: string;
  /** The control offers nothing outside `COMPLETED` (R3.1) — self-gated, not the row's job. */
  status: CleaningTaskStatus;
  /** The task's current verdict, used only to disable the button that would resend it (R3.6). */
  validationStatus: CleaningValidationStatus;
  /** This row's own validation is in flight. */
  isPending: boolean;
  /**
   * Some validation — this row's or another's — is in flight. The view owns a single
   * mutation, so a second one would detach the first and swallow its rejection (mirrors
   * `AssignCleanerControl.isBlocked`).
   */
  isBlocked: boolean;
  onValidate: (input: { taskId: string; verdict: CleaningValidationVerdict }) => void;
}

export function ValidateCleaningControl({
  taskId,
  status,
  validationStatus,
  isPending,
  isBlocked,
  onValidate,
}: ValidateCleaningControlProps) {
  const { t } = useTranslation("cleaning");

  if (status !== "COMPLETED") {
    return null;
  }

  const noticeId = `validate-notice-${taskId}`;
  const disabledCommon = isPending || isBlocked;
  const passedDisabled = disabledCommon || validationStatus === "PASSED";
  const failedDisabled = disabledCommon || validationStatus === "FAILED";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={passedDisabled}
          aria-describedby={noticeId}
          onClick={() => onValidate({ taskId, verdict: "PASSED" })}
        >
          {t("validate.passed")}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={failedDisabled}
          aria-describedby={noticeId}
          onClick={() => onValidate({ taskId, verdict: "FAILED" })}
        >
          {t("validate.failed")}
        </Button>
      </div>
      {/*
        Static text and not a `title`: the view is mobile-first, where there is no hover
        (design D6). Unlike `AssignCleanerControl`'s blocked reason, this is not
        conditional — the two consequences hold every time the control is offered.
      */}
      <p id={noticeId} className="text-body-base text-muted-foreground">
        {t("validate.notice")}
      </p>
    </div>
  );
}
