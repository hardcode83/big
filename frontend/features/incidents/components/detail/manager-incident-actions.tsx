"use client";

import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ApiError } from "@/lib/api";

import type {
  IncidentCategory,
  IncidentDetailDto,
  IncidentSeverity,
  TechnicianSummary,
} from "../../data";
import {
  MAX_ASSIGNMENT_NOTE_LENGTH,
  hasControlCharacters,
} from "../../lib/assignment-note";
import { isPositiveDecimal } from "../../lib/cost-format";
import { managerActionMessage } from "../../lib/manager-action-error";
import {
  managerActions,
  managerStatusNote,
  type ManagerAction,
} from "../../lib/manager-actions";
import {
  useAssignIncident,
  useCancelIncident,
  useClassifyIncident,
  useTechnicianDirectory,
  useTriageIncident,
} from "../../hooks/use-incident-management";

const CATEGORIES: readonly IncidentCategory[] = [
  "ACCESS",
  "LOCK",
  "WIFI",
  "ELECTRICITY",
  "WATER",
  "PLUMBING",
  "HVAC",
  "APPLIANCE",
  "NOISE",
  "CLEANING",
  "DAMAGE",
  "SAFETY",
  "OTHER",
];

const SEVERITIES: readonly IncidentSeverity[] = [
  "LOW",
  "MEDIUM",
  "HIGH",
  "CRITICAL",
];

function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/**
 * Turns a bare `ManagerActionErrorReason` into the localized text (design D9,
 * R2.5, R6.1): the two `422` reasons live under `manager.errors.*`, the four
 * `409`/conflict-family reasons under `manager.conflict.*`. Never renders
 * `error.message` (R6.1, R2.5).
 */
function reasonText(
  t: (key: string) => string,
  error: unknown,
  status: IncidentDetailDto["status"],
  action: ManagerAction,
): string | undefined {
  const reason = managerActionMessage(error, status, action);
  if (!reason) return undefined;
  if (reason === "invalid-technician" || reason === "invalid-cost") {
    return t(`manager.errors.${reason}`);
  }
  return t(`manager.conflict.${reason}`);
}

/**
 * The manager's mutation controls for `/incidents/[id]` (proposal R1-R6,
 * design D13). Mounted by `IncidentDetailView` only behind
 * `useHasPermission("MANAGE_INCIDENTS")` — a caller without the permission
 * never imports this component, so there is no reserved gap (R1.1, R1.2).
 *
 * Follows the shape of `TechCycleActions`: `manager-actions.ts` decides which
 * of classify/assign/triage/cancel are on offer for the current status
 * (R1.3-R1.5), this component only renders what that table returns — it is
 * presentation of the contract, never authorization (R1.6, `steering/frontend.md`).
 * A `403` from any of the four mutations hides the whole section and shows the
 * same "sin permiso" text the read-only detail already uses (R6.2); `401` has
 * no variant of its own here (delegated to the session-expiry flow).
 */
export function ManagerIncidentActions({
  incident,
}: {
  incident: IncidentDetailDto;
}) {
  const { t } = useTranslation("incidents");
  const classify = useClassifyIncident();
  const triage = useTriageIncident();
  const assign = useAssignIncident();
  const cancel = useCancelIncident();
  const technicians = useTechnicianDirectory();

  const [assignOpen, setAssignOpen] = useState(false);
  const [triageOpen, setTriageOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);

  const forbidden = [classify.error, triage.error, assign.error, cancel.error].some(
    isForbidden,
  );

  if (forbidden) {
    return (
      <section aria-label={t("manager.title")}>
        <Card className="p-4">
          <p className="text-body-base text-muted-foreground">
            {t("fields.forbidden")}
          </p>
        </Card>
      </section>
    );
  }

  const actions = managerActions(incident.status);
  const statusNote = managerStatusNote(incident.status);

  if (actions.length === 0) {
    // A mutation attempted moments ago can still be holding a `409` whose
    // reason (typically "closed") explains *why* nothing is left to do —
    // shown here instead of the generic `manager.none`, same as
    // `TechCycleActions` surfaces `cycleError` above its own no-actions text.
    const lastError = (
      [
        ["classify", classify.error],
        ["triage", triage.error],
        ["assign", assign.error],
        ["cancel", cancel.error],
      ] as const
    )
      .map(([action, error]) => reasonText(t, error, incident.status, action))
      .find((text): text is string => Boolean(text));
    return (
      <section aria-label={t("manager.title")}>
        <Card className="flex flex-col gap-2 p-4">
          {lastError ? (
            <p role="alert" className="text-body-base text-state-error-text">
              {lastError}
            </p>
          ) : null}
          <p className="text-body-base text-muted-foreground">
            {t("manager.none")}
          </p>
        </Card>
      </section>
    );
  }

  const classifyError = reasonText(t, classify.error, incident.status, "classify");
  // Gated on the CURRENT `incident.status` prop, not on `classify.data`/
  // `triage.data` (a snapshot frozen at whichever moment that mutation last
  // resolved): a later, DIFFERENT mutation (e.g. a triage that classifies via
  // `classify_by_triage`) never touches the other mutation's `isSuccess`/
  // `data`, so a snapshot-based check would keep showing a stale post-action
  // message after the incident has actually moved on. `incident.status`
  // always reflects the latest refetch (every mutation's `onSettled`
  // invalidates `incidentsKeys.detail`), so once a superseding mutation
  // changes the status, the `isSuccess && status === "..."` pair for the
  // ORIGINAL mutation stops matching on its own — no cross-mutation reset
  // needed. `isSuccess` alone still guards against showing this on a plain
  // page load where the incident happens to already be `OPEN` with no action
  // taken (fixes review finding: stale post-action messages surviving a
  // superseding mutation).
  const classifyStillOpen = classify.isSuccess && incident.status === "OPEN";
  const triageAwaitingApproval =
    triage.isSuccess && incident.status === "AWAITING_OWNER_APPROVAL";
  const triageStillOpen = triage.isSuccess && incident.status === "OPEN";

  return (
    <section aria-label={t("manager.title")}>
      <Card className="flex flex-col gap-4 p-4">
        <h2 className="text-body-lg font-semibold text-foreground">
          {t("manager.title")}
        </h2>

        {statusNote ? (
          <p role="note" className="text-body-base text-muted-foreground">
            {t(`manager.statusNote.${statusNote}`)}
          </p>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {actions.includes("classify") ? (
            <Button
              type="button"
              className="tap-target"
              disabled={classify.isPending}
              onClick={() => classify.mutate({ incidentId: incident.id })}
            >
              {classify.isPending
                ? t("manager.actions.sending")
                : t("manager.actions.classify")}
            </Button>
          ) : null}
          {actions.includes("assign") ? (
            <Button
              type="button"
              variant="outline"
              className="tap-target"
              onClick={() => setAssignOpen(true)}
            >
              {incident.assignedTechnicianId
                ? t("manager.actions.reassign")
                : t("manager.actions.assign")}
            </Button>
          ) : null}
          {actions.includes("triage") ? (
            <Button
              type="button"
              variant="outline"
              className="tap-target"
              onClick={() => setTriageOpen(true)}
            >
              {t("manager.actions.triage")}
            </Button>
          ) : null}
          {actions.includes("cancel") ? (
            <Button
              type="button"
              variant="destructive"
              className="tap-target"
              onClick={() => setCancelOpen(true)}
            >
              {t("manager.actions.cancel")}
            </Button>
          ) : null}
        </div>

        {classifyError ? (
          <p role="alert" className="text-body-base text-state-error-text">
            {classifyError}
          </p>
        ) : null}
        {classifyStillOpen ? (
          <p role="status" className="text-body-base text-muted-foreground">
            {t("manager.postClassify.stillOpen")}
          </p>
        ) : null}
        {triageAwaitingApproval ? (
          <p role="status" className="text-body-base text-muted-foreground">
            {t("manager.postTriage.awaitingApproval")}
          </p>
        ) : null}
        {triageStillOpen ? (
          <p role="status" className="text-body-base text-muted-foreground">
            {t("manager.postTriage.stillOpen")}
          </p>
        ) : null}
      </Card>

      <AssignSheet
        open={assignOpen}
        onOpenChange={setAssignOpen}
        incident={incident}
        technicians={technicians.data ?? []}
        mutation={assign}
      />
      <TriageSheet
        open={triageOpen}
        onOpenChange={setTriageOpen}
        incident={incident}
        mutation={triage}
      />
      <CancelDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        incident={incident}
        mutation={cancel}
      />
    </section>
  );
}

interface AssignSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  incident: IncidentDetailDto;
  technicians: readonly TechnicianSummary[];
  mutation: ReturnType<typeof useAssignIncident>;
}

/**
 * Assign/reassign a technician (R2.1-R2.5, design D13). Native `<select>`
 * narrowed to `ACTIVE` technicians (`AssignCleanerControl`'s precedent: an
 * arrow-key walk through the options fires `change` per option, so the
 * confirm button is what actually submits) — inactive technicians resolve by
 * name elsewhere (`DetailAssignedTechnicianBlock`, D10) but are never offered
 * here. Starts unselected regardless of whether this is an assign or a
 * reassign (R2.2): a preselected value would leave a confirm button live
 * with zero interaction.
 */
function AssignSheet({
  open,
  onOpenChange,
  incident,
  technicians,
  mutation,
}: AssignSheetProps) {
  const { t } = useTranslation("incidents");
  const closeLabel = incident.assignedTechnicianId
    ? t("manager.assign.titleReassign")
    : t("manager.assign.title");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" closeLabel={closeLabel} className="flex flex-col gap-4">
        {open ? (
          <AssignSheetBody
            key="open"
            incident={incident}
            technicians={technicians}
            mutation={mutation}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

interface AssignSheetBodyProps {
  incident: IncidentDetailDto;
  technicians: readonly TechnicianSummary[];
  mutation: ReturnType<typeof useAssignIncident>;
  onClose: () => void;
}

function validateAssignmentNote(value: string): "too-long" | "control-chars" | null {
  if (value.length > MAX_ASSIGNMENT_NOTE_LENGTH) return "too-long";
  if (hasControlCharacters(value)) return "control-chars";
  return null;
}

function AssignSheetBody({
  incident,
  technicians,
  mutation,
  onClose,
}: AssignSheetBodyProps) {
  const { t } = useTranslation("incidents");
  const [technicianId, setTechnicianId] = useState("");
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<"too-long" | "control-chars" | null>(
    null,
  );
  const submittingRef = useRef(false);
  const selectId = useId();
  const noteId = useId();
  const noteErrorId = useId();

  const candidates = technicians.filter((technician) => technician.isActive);
  const isReassign = incident.assignedTechnicianId !== null;
  const canSubmit =
    !mutation.isPending && technicianId !== "" && validateAssignmentNote(note) === null;

  function handleSubmit() {
    const validation = validateAssignmentNote(note);
    if (technicianId === "" || validation !== null) {
      setNoteError(validation);
      return;
    }
    if (submittingRef.current) return;
    submittingRef.current = true;
    mutation.mutate(
      {
        incidentId: incident.id,
        technicianId,
        ...(note.trim() !== "" ? { assignmentNote: note } : {}),
      },
      {
        onSuccess: () => onClose(),
        onError: () => {
        },
        onSettled: () => {
          submittingRef.current = false;
        },
      },
    );
  }

  const serverError = reasonText(t, mutation.error, incident.status, "assign");

  return (
    <>
      <SheetHeader>
        <SheetTitle>
          {isReassign ? t("manager.assign.titleReassign") : t("manager.assign.title")}
        </SheetTitle>
      </SheetHeader>

      {isReassign ? (
        <p role="note" className="text-body-base text-muted-foreground">
          {t("manager.assign.reassignWarning")}
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <label htmlFor={selectId} className="text-sm font-medium">
          {t("manager.assign.technicianLabel")}
        </label>
        <select
          id={selectId}
          autoFocus
          className="tap-target w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          value={technicianId}
          disabled={mutation.isPending}
          onChange={(event) => setTechnicianId(event.target.value)}
        >
          <option value="">{t("manager.assign.technicianPlaceholder")}</option>
          {candidates.map((technician) => (
            <option key={technician.id} value={technician.id}>
              {technician.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={noteId} className="text-sm font-medium">
          {t("manager.assign.noteLabel")}
        </label>
        <textarea
          id={noteId}
          value={note}
          rows={4}
          disabled={mutation.isPending}
          className="min-h-24 w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          placeholder={t("manager.assign.notePlaceholder")}
          aria-describedby={noteError ? noteErrorId : undefined}
          aria-invalid={noteError !== null}
          onChange={(event) => {
            setNote(event.target.value);
            if (noteError && validateAssignmentNote(event.target.value) === null) {
              setNoteError(null);
            }
          }}
        />
        <p className="text-xs text-muted-foreground">{t("manager.assign.noteHelp")}</p>
        {noteError ? (
          <p id={noteErrorId} role="alert" className="text-xs text-destructive">
            {t(
              `manager.assign.errors.${
                noteError === "too-long" ? "noteTooLong" : "noteControlChars"
              }`,
            )}
          </p>
        ) : null}
      </div>

      {serverError ? (
        <p role="alert" className="text-xs text-destructive">
          {serverError}
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          className="tap-target"
          onClick={handleSubmit}
          disabled={!canSubmit}
          aria-busy={mutation.isPending}
        >
          {mutation.isPending ? t("manager.assign.sending") : t("manager.assign.confirm")}
        </Button>
      </div>
    </>
  );
}

interface TriageSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  incident: IncidentDetailDto;
  mutation: ReturnType<typeof useTriageIncident>;
}

/**
 * Triage: correct category, severity and/or estimated cost (R3.1-R3.4, design
 * D13). Fields are precharged with the incident's current values and only
 * the ones the manager actually changes travel in the `PATCH` body
 * (`useTriageIncident` already sends only what it is given — this is what
 * decides what it is given). The cost is validated client-side with
 * `isPositiveDecimal` before it can be submitted (R3.2).
 */
function TriageSheet({ open, onOpenChange, incident, mutation }: TriageSheetProps) {
  const { t } = useTranslation("incidents");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        closeLabel={t("manager.triage.title")}
        className="flex flex-col gap-4"
      >
        {open ? (
          <TriageSheetBody
            key="open"
            incident={incident}
            mutation={mutation}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

interface TriageSheetBodyProps {
  incident: IncidentDetailDto;
  mutation: ReturnType<typeof useTriageIncident>;
  onClose: () => void;
}

function TriageSheetBody({ incident, mutation, onClose }: TriageSheetBodyProps) {
  const { t } = useTranslation("incidents");
  const [category, setCategory] = useState<IncidentCategory>(incident.category);
  const [severity, setSeverity] = useState<IncidentSeverity>(incident.severity);
  const initialCost = incident.estimatedCost ?? "";
  const [cost, setCost] = useState(initialCost);
  const [costError, setCostError] = useState(false);
  const submittingRef = useRef(false);
  const categoryId = useId();
  const severityId = useId();
  const costId = useId();
  const costErrorId = useId();

  const trimmedCost = cost.trim();
  const costChanged = trimmedCost !== initialCost;
  const costValid = !costChanged || isPositiveDecimal(trimmedCost);
  const hasChanges =
    category !== incident.category || severity !== incident.severity || costChanged;
  const canSubmit = !mutation.isPending && hasChanges && costValid;

  function handleSubmit() {
    if (!costValid) {
      setCostError(true);
      return;
    }
    if (!hasChanges || submittingRef.current) return;
    submittingRef.current = true;
    mutation.mutate(
      {
        incidentId: incident.id,
        ...(category !== incident.category ? { category } : {}),
        ...(severity !== incident.severity ? { severity } : {}),
        ...(costChanged ? { estimatedCost: trimmedCost } : {}),
      },
      {
        onSuccess: () => onClose(),
        onError: () => {
        },
        onSettled: () => {
          submittingRef.current = false;
        },
      },
    );
  }

  const serverError = reasonText(t, mutation.error, incident.status, "triage");

  return (
    <>
      <SheetHeader>
        <SheetTitle>{t("manager.triage.title")}</SheetTitle>
      </SheetHeader>

      <div className="flex flex-col gap-2">
        <label htmlFor={categoryId} className="text-sm font-medium">
          {t("manager.triage.categoryLabel")}
        </label>
        <select
          id={categoryId}
          autoFocus
          value={category}
          disabled={mutation.isPending}
          className="tap-target w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          onChange={(event) => setCategory(event.target.value as IncidentCategory)}
        >
          {CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {t(`category.${value}`)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={severityId} className="text-sm font-medium">
          {t("manager.triage.severityLabel")}
        </label>
        <select
          id={severityId}
          value={severity}
          disabled={mutation.isPending}
          className="tap-target w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          onChange={(event) => setSeverity(event.target.value as IncidentSeverity)}
        >
          {SEVERITIES.map((value) => (
            <option key={value} value={value}>
              {t(`severity.${value}`)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={costId} className="text-sm font-medium">
          {t("manager.triage.costLabel")}
        </label>
        <input
          id={costId}
          type="number"
          inputMode="decimal"
          min="0"
          step="0.01"
          value={cost}
          disabled={mutation.isPending}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          placeholder={t("manager.triage.costPlaceholder")}
          aria-describedby={costError ? costErrorId : undefined}
          aria-invalid={costError}
          onChange={(event) => {
            setCost(event.target.value);
            const next = event.target.value.trim();
            if (costError && (next === initialCost || isPositiveDecimal(next))) {
              setCostError(false);
            }
          }}
        />
        <p className="text-xs text-muted-foreground">{t("manager.triage.costHelp")}</p>
        {costError ? (
          <p id={costErrorId} role="alert" className="text-xs text-destructive">
            {t("manager.triage.errors.invalidCost")}
          </p>
        ) : null}
      </div>

      {serverError ? (
        <p role="alert" className="text-xs text-destructive">
          {serverError}
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          className="tap-target"
          onClick={handleSubmit}
          disabled={!canSubmit}
          aria-busy={mutation.isPending}
        >
          {mutation.isPending ? t("manager.triage.sending") : t("manager.triage.confirm")}
        </Button>
      </div>
    </>
  );
}

interface CancelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  incident: IncidentDetailDto;
  mutation: ReturnType<typeof useCancelIncident>;
}

/**
 * Cancel with confirmation (R5.1-R5.3, design D13). No reason is asked for or
 * sent — the contract has none. `AlertDialogAction` is Radix's
 * `Dialog.Close` under the hood, which closes unconditionally unless the
 * click handler calls `event.preventDefault()`; this one does, and only
 * calls `onOpenChange(false)` itself once the mutation actually succeeds, so
 * a `409` keeps the dialog open with the reason shown instead of silently
 * closing on a failed cancel.
 */
function CancelDialog({ open, onOpenChange, incident, mutation }: CancelDialogProps) {
  const { t } = useTranslation("incidents");
  const submittingRef = useRef(false);

  function handleConfirm(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    mutation.mutate(
      { incidentId: incident.id },
      {
        onSuccess: () => onOpenChange(false),
        onError: () => {
        },
        onSettled: () => {
          submittingRef.current = false;
        },
      },
    );
  }

  const errorMessage = reasonText(t, mutation.error, incident.status, "cancel");

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("manager.cancel.title")}</AlertDialogTitle>
          <AlertDialogDescription>{t("manager.cancel.body")}</AlertDialogDescription>
        </AlertDialogHeader>
        {errorMessage ? (
          <p role="alert" className="text-body-base text-state-error-text">
            {errorMessage}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel>{t("manager.cancel.keep")}</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={mutation.isPending}
            aria-busy={mutation.isPending}
          >
            {mutation.isPending ? t("manager.cancel.sending") : t("manager.cancel.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
