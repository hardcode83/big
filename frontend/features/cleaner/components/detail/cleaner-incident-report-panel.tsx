"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import { useCleanerTaskCycleAction } from "../../hooks/use-cleaner-cycle";
import { mapCleanerError } from "../../lib/error-mapping";
import type { CleaningIncidentReportAck } from "../../data";

/** `MAX_INCIDENT_TITLE` is imported from the backend (D7 of the proposal). */
const MAX_TITLE = 300;
/** `MAX_INCIDENT_DESCRIPTION` is imported from the backend (D7 of the proposal). */
const MAX_DESCRIPTION = 5000;

/** Statuses where reporting an incident is on offer (R6.1). */
const INCIDENT_REPORTABLE_STATUSES = new Set([
  "ASSIGNED",
  "ACCEPTED",
  "IN_PROGRESS",
] as const);

/**
 * The inline two-field incident report panel (R6.1, R6.2, R6.3, R6.5, D11).
 *
 * Native `<input maxLength={300}>` for the title and `<textarea
 * maxLength={5000}>` for the description. Local validation mirrors
 * `SingleLineText` / `MultiLineText` (R6.2): the title is trimmed, has no
 * control characters; the description accepts tabs and newlines. Submission is
 * blocked while either bound is violated — the `422` the backend would return
 * is prevented, not reacted to.
 *
 * On `201`, the panel renders only the three-field ack (`id`, `status`,
 * `created_at`). The title and description are **not** re-rendered (R6.3).
 *
 * The component returns `null` when the task's status is not one of
 * `INCIDENT_REPORTABLE_STATUSES` (R6.1).
 */
export interface CleanerIncidentReportPanelProps {
  taskId: string;
  status: string;
}

export function CleanerIncidentReportPanel({
  taskId,
  status,
}: CleanerIncidentReportPanelProps) {
  const { t, i18n } = useTranslation("cleaner");
  const locale = i18n.language;
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [descriptionError, setDescriptionError] = useState<string | null>(
    null,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [ack, setAck] = useState<CleaningIncidentReportAck | null>(null);
  const mutation = useCleanerTaskCycleAction("reportIncident");

  const statusKey = status as keyof typeof INCIDENT_REPORTABLE_STATUSES;
  if (!INCIDENT_REPORTABLE_STATUSES.has(statusKey)) {
    return null;
  }

  function validateTitle(value: string): string | null {
    const trimmed = value.trim();
    if (trimmed.length === 0) {
      return "incidentReport.errors.titleRequired";
    }
    if (trimmed.length > MAX_TITLE) {
      return "incidentReport.errors.titleTooLong";
    }
    // No control characters, mirroring `SingleLineText`. The \p{Cc}
    // unicode class covers U+0000–U+001F and U+007F–U+009F; tabs and newlines
    // are not control characters here (the description accepts them).
    if (/\p{Cc}/u.test(trimmed)) {
      return "incidentReport.errors.titleRequired";
    }
    return null;
  }

  function validateDescription(value: string): string | null {
    if (value.trim().length === 0) {
      return "incidentReport.errors.descriptionRequired";
    }
    if (value.length > MAX_DESCRIPTION) {
      return "incidentReport.errors.descriptionTooLong";
    }
    return null;
  }

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const titleErr = validateTitle(title);
    const descErr = validateDescription(description);
    setTitleError(titleErr);
    setDescriptionError(descErr);
    if (titleErr || descErr) {
      return;
    }
    setSubmitError(null);
    mutation.mutate(
      {
        taskId,
        input: { title: title.trim(), description },
      },
      {
        onSuccess: (data) => {
          setAck(data as CleaningIncidentReportAck);
          setOpen(false);
          setTitle("");
          setDescription("");
        },
        onError: (error) => {
          const map = mapCleanerError(error, "reportIncident");
          setSubmitError(map.messageKey);
        },
      },
    );
  }

  if (ack) {
    return (
      <section
        aria-labelledby="cleaner-incident-ack-heading"
        className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
      >
        <h2
          id="cleaner-incident-ack-heading"
          className="text-sm font-semibold text-foreground"
        >
          {t("incidentReport.ack.title")}
        </h2>
        <dl className="grid grid-cols-1 gap-2 text-sm">
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">
              {t("incidentReport.ack.id")}
            </dt>
            <dd className="font-mono text-xs">{ack.id}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">
              {t("incidentReport.ack.status")}
            </dt>
            <dd>{ack.status}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-muted-foreground">
              {t("incidentReport.ack.createdAt")}
            </dt>
            <dd>
              {new Intl.DateTimeFormat(locale, {
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(ack.createdAt))}
            </dd>
          </div>
        </dl>
      </section>
    );
  }

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        onClick={() => setOpen(true)}
        data-testid="cleaner-incident-report-trigger"
      >
        {t("actions.reportIncident")}
      </Button>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      aria-labelledby="cleaner-incident-report-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-incident-report-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("incidentReport.title")}
      </h2>
      <div className="flex flex-col gap-1">
        <label
          htmlFor="cleaner-incident-title"
          className="text-xs font-medium text-muted-foreground"
        >
          {t("incidentReport.titleField")}
        </label>
        <input
          id="cleaner-incident-title"
          type="text"
          maxLength={MAX_TITLE}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          className="rounded-md border bg-background px-2 py-1 text-sm"
        />
        {titleError ? (
          <span role="alert" className="text-xs text-destructive">
            {t(titleError)}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-1">
        <label
          htmlFor="cleaner-incident-description"
          className="text-xs font-medium text-muted-foreground"
        >
          {t("incidentReport.descriptionField")}
        </label>
        <textarea
          id="cleaner-incident-description"
          rows={4}
          maxLength={MAX_DESCRIPTION}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          className="rounded-md border bg-background px-2 py-1 text-sm"
        />
        {descriptionError ? (
          <span role="alert" className="text-xs text-destructive">
            {t(descriptionError)}
          </span>
        ) : null}
      </div>
      {submitError ? (
        <span role="alert" className="text-xs text-destructive">
          {t(submitError)}
        </span>
      ) : null}
      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          onClick={() => setOpen(false)}
        >
          {t("actions.reject")}
        </Button>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending
            ? t("incidentReport.submitting")
            : t("incidentReport.submit")}
        </Button>
      </div>
    </form>
  );
}