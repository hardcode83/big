"use client";

import { useId, useRef, useState } from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { CleaningTask, CreateCleaningTaskInput } from "../data";
import { usePropertyDirectory } from "../hooks/use-cleaning-data";
import { warnsNotAssignable } from "../lib/assignable-property-state";

/**
 * Manual creation of a cleaning task (R1.1–R1.4, R2.1–R2.4), as a disclosure panel
 * in the document flow, not a Sheet (design D1): `CleaningView` mounts it above the
 * list, always present, and this component owns only the button that
 * expands/collapses its own form — the same region hides again once the panel
 * closes, instead of stacking an overlay above the view's single live region.
 *
 * The mutation itself is NOT instantiated here: `CleaningView` owns
 * `useCreateCleaningTask()` (design D4) because the same instance also feeds the
 * view's one `role="status" aria-live="polite"` region — this component would
 * otherwise need a second place to announce from, which R1.5 forbids. This
 * component only calls `mutation.mutate` and closes itself on success.
 */
export interface CreateCleaningTaskPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mutation: UseMutationResult<CleaningTask, Error, CreateCleaningTaskInput>;
}

export function CreateCleaningTaskPanel({
  open,
  onOpenChange,
  mutation,
}: CreateCleaningTaskPanelProps) {
  const { t } = useTranslation("cleaning");
  const contentId = useId();

  return (
    <div className="flex flex-col gap-3">
      <Button
        type="button"
        variant="outline"
        className="self-start"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => onOpenChange(!open)}
      >
        {open ? t("create.close") : t("create.open")}
      </Button>
      {open ? (
        <div id={contentId}>
          {/* Keyed remount (like `CancelCleaningDialogBody`): every time the panel
              opens it starts from a blank form, with no `useEffect` reset needed. */}
          <CreateCleaningTaskPanelBody
            key="open"
            mutation={mutation}
            onDone={() => onOpenChange(false)}
          />
        </div>
      ) : null}
    </div>
  );
}

interface CreateCleaningTaskPanelBodyProps {
  mutation: UseMutationResult<CleaningTask, Error, CreateCleaningTaskInput>;
  onDone: () => void;
}

function CreateCleaningTaskPanelBody({
  mutation,
  onDone,
}: CreateCleaningTaskPanelBodyProps) {
  const { t } = useTranslation("cleaning");
  // Same query the filter bar and every row already read (design D9) — this call
  // shares the cache key, so it costs no extra request.
  const propertyDirectory = usePropertyDirectory();
  const properties = propertyDirectory.data ?? [];

  const [propertyId, setPropertyId] = useState("");
  const [scheduledStart, setScheduledStart] = useState("");
  const [scheduledEnd, setScheduledEnd] = useState("");
  // Guards a double `mutate` the same way `CancelCleaningDialogBody` does:
  // `mutation.isPending` only flips on the next commit, so two submits inside the
  // same frame would both reach `mutate` without this ref.
  const submittingRef = useRef(false);

  const propertyFieldId = useId();
  const startFieldId = useId();
  const endFieldId = useId();

  /**
   * R2.3, fail-open: an id not (yet) in the directory — catalog still loading or
   * failed — resolves to `undefined` here, and `warnsNotAssignable` treats an
   * `undefined` state as "no warning", the same policy `assignment_blocker`
   * documents for `property_state is None`. The warning is a courtesy only: it
   * never blocks submission (R2.2).
   */
  const selectedProperty = properties.find(
    (property) => property.id === propertyId,
  );
  const showNotAssignableWarning = warnsNotAssignable(
    selectedProperty?.currentOperationalState,
  );

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!propertyId || submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    const start = toInstant(scheduledStart);
    const end = toInstant(scheduledEnd);
    const input: CreateCleaningTaskInput = {
      propertyId,
      ...(start !== undefined ? { scheduledStart: start } : {}),
      ...(end !== undefined ? { scheduledEnd: end } : {}),
    };
    mutation.mutate(input, {
      onSuccess: () => onDone(),
      onSettled: () => {
        submittingRef.current = false;
      },
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface/60 p-3"
    >
      <div className="flex flex-col gap-1">
        <label
          htmlFor={propertyFieldId}
          className="text-xs font-medium text-muted-foreground"
        >
          {t("create.fields.property.label")}
        </label>
        <select
          id={propertyFieldId}
          required
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={propertyId}
          onChange={(event) => setPropertyId(event.target.value)}
        >
          <option value="">{t("create.fields.property.placeholder")}</option>
          {properties.map((property) => (
            <option key={property.id} value={property.id}>
              {property.internalCode} {t("separator")} {property.name}
            </option>
          ))}
        </select>
      </div>
      {showNotAssignableWarning ? (
        <p className="rounded-md border border-state-warning/40 bg-state-warning/15 p-2 text-xs text-state-warning-text">
          {t("create.warning.notAssignable")}
        </p>
      ) : null}
      <div className="flex flex-col gap-1">
        <label
          htmlFor={startFieldId}
          className="text-xs font-medium text-muted-foreground"
        >
          {t("create.fields.scheduledStart.label")}
        </label>
        <input
          id={startFieldId}
          type="datetime-local"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={scheduledStart}
          onChange={(event) => setScheduledStart(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label
          htmlFor={endFieldId}
          className="text-xs font-medium text-muted-foreground"
        >
          {t("create.fields.scheduledEnd.label")}
        </label>
        <input
          id={endFieldId}
          type="datetime-local"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={scheduledEnd}
          onChange={(event) => setScheduledEnd(event.target.value)}
        />
      </div>
      <Button type="submit" disabled={mutation.isPending || !propertyId}>
        {mutation.isPending ? t("create.sending") : t("create.confirm")}
      </Button>
    </form>
  );
}

/**
 * The exact conversion `features/tech/components/detail/tech-eta-field.tsx`
 * documents as `etaToInstant`: a `datetime-local` value is read in the device's
 * zone and sent with `Z`. Empty means "omit the field", never `null` (R1.2). Kept
 * local rather than imported across features (`tech` and `cleaning` do not share
 * this helper as a dependency) — same mechanism, independent copy.
 */
function toInstant(value: string): string | undefined {
  if (!value) {
    return undefined;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    // Let the server refuse an unparseable value rather than inventing a
    // client-side rule for it — not this component's call to reject.
    return value;
  }
  return date.toISOString();
}
