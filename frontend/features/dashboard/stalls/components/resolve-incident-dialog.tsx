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

import { useResolveIncident } from "@/features/incidents";

/**
 * Two decimals with an optional leading digit; accepts both `0.50` and
 * `.50` and rejects commas, exponents and trailing punctuation. The backend
 * schema accepts `number | string` (openapi.d.ts:3284), so the validated
 * value travels to the wire as a string to keep the formatting verbatim.
 */
const POSITIVE_DECIMAL = /^\d+(\.\d{1,2})?$|^\.\d{1,2}$/;

/**
 * Modal that confirms an incident resolution from the dashboard card
 * (proposal `blocked-transitions-web` R2.3, R3.1, D7).
 *
 * Asks for the **required** `final_cost` (`maintenance.md` R4.2) as a
 * positive decimal with up to two decimals. The HTML input gives the mobile
 * wheel for free (R5.3 of the project steering), and the client-side regex
 * is what makes a `422` impossible from this UI — same gate as the cancel
 * dialog.
 *
 * Submit is disabled while the mutation is in flight (`isPending`); the close
 * button stays enabled so the user can abandon the action without waiting.
 *
 * The dialog body lives behind a `key={open ? "open" : "closed"}` switch so
 * the form is fresh every time the dialog opens — no `useEffect` reset, no
 * cascading render.
 */
export interface ResolveIncidentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  incidentId: string;
  trigger: string;
  blockingState: string;
}

export function ResolveIncidentDialog({
  open,
  onOpenChange,
  incidentId,
  trigger,
  blockingState,
}: ResolveIncidentDialogProps) {
  const { t } = useTranslation("dashboard");
  const mutation = useResolveIncident();
  const closeLabel = t("card.blocked.resolveIncident.dialog.title");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        closeLabel={closeLabel}
        className="flex flex-col gap-4"
      >
        {open ? (
          <ResolveIncidentDialogBody
            key="open"
            incidentId={incidentId}
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
  incidentId: string;
  trigger: string;
  blockingState: string;
  mutation: ReturnType<typeof useResolveIncident>;
  onClose: () => void;
}

function ResolveIncidentDialogBody({
  incidentId,
  trigger,
  blockingState,
  mutation,
  onClose,
}: BodyProps) {
  const { t } = useTranslation("dashboard");
  const [value, setValue] = useState("");
  const [validationError, setValidationError] = useState(false);
  const inputId = useId();
  const inputHelpId = useId();
  const inputErrorId = useId();

  const parsed = POSITIVE_DECIMAL.test(value.trim());
  const canSubmit = !mutation.isPending && parsed;
  const describedBy = [
    inputHelpId,
    validationError ? inputErrorId : null,
  ]
    .filter((entry): entry is string => Boolean(entry))
    .join(" ") || undefined;

  function handleSubmit() {
    if (!canSubmit) {
      setValidationError(true);
      return;
    }
    mutation.mutate(
      { incidentId, finalCost: value.trim() },
      {
        onSuccess: () => onClose(),
        onError: () => {
          // R3.3: localized error renders beneath the input; do not close.
        },
      },
    );
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle>{t("card.blocked.resolveIncident.dialog.title")}</SheetTitle>
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
        <label htmlFor={inputId} className="text-sm font-medium">
          {t("card.blocked.resolveIncident.dialog.finalCost.label")}
        </label>
        <input
          id={inputId}
          autoFocus
          type="number"
          inputMode="decimal"
          min="0"
          step="0.01"
          value={value}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          aria-describedby={describedBy}
          aria-invalid={validationError}
          placeholder={t(
            "card.blocked.resolveIncident.dialog.finalCost.placeholder",
          )}
          onChange={(event) => {
            setValue(event.target.value);
            if (
              validationError &&
              POSITIVE_DECIMAL.test(event.target.value.trim())
            ) {
              setValidationError(false);
            }
          }}
        />
        <p id={inputHelpId} className="text-xs text-muted-foreground">
          {t("card.blocked.resolveIncident.dialog.finalCost.help")}
        </p>
        {validationError ? (
          <p
            id={inputErrorId}
            role="alert"
            className="text-xs text-destructive"
          >
            {t("card.blocked.resolveIncident.dialog.error.positive")}
          </p>
        ) : null}
        {mutation.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {t("card.blocked.resolveIncident.dialog.error.generic")}
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
            ? t("card.blocked.resolveIncident.dialog.sending")
            : t("card.blocked.resolveIncident.dialog.confirm")}
        </Button>
      </div>
    </>
  );
}