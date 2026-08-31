"use client";

import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";

import type { PhotoRequirementsResponse } from "../../data";

/**
 * The photo-categories block (R2.4). One row per category in the order the
 * template declares, with the `required` marker and the coverage indicator.
 *
 * The upload button per category is mounted by section 7; this component stays
 * read-only and just reports `uploaded` (`covered`) vs. (`pending`).
 *
 * An unknown `photo_type` (a deploy-skew window between the wire and the
 * compiled frontend) is **not** rendered as a button — it falls into the
 * "degraded row" branch (D17): the row exists, the label is what the backend
 * sent, but the upload button is not painted. The cleaner cannot cover a
 * `photo_type` the compiled frontend does not know.
 */
export interface CleanerTaskPhotoRequirementsProps {
  requirements: PhotoRequirementsResponse;
  /**
   * Render-prop for the per-row upload action. Section 7 wires this to
   * `<CleanerTaskPhotoUploadButton />`; section 5 keeps it `undefined` so the
   * block renders read-only.
   */
  renderUpload?: (entry: PhotoRequirementsResponse["data"][number]) => React.ReactNode;
  /**
   * When `false`, no upload button renders (the task is not `IN_PROGRESS`).
   * Defaults to `false`.
   */
  canUpload?: boolean;
}

export function CleanerTaskPhotoRequirements({
  requirements,
  renderUpload,
  canUpload = false,
}: CleanerTaskPhotoRequirementsProps) {
  const { t } = useTranslation(["cleaner", "states"]);

  if (requirements.data.length === 0) {
    return (
      <section
        aria-labelledby="cleaner-photo-reqs-heading"
        className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
      >
        <h2
          id="cleaner-photo-reqs-heading"
          className="text-sm font-semibold text-foreground"
        >
          {t("cleaner:photoRequirements.title")}
        </h2>
        <EmptyState
          title={t("cleaner:photoRequirements.empty.title")}
          description={t("cleaner:photoRequirements.empty.description")}
        />
      </section>
    );
  }

  return (
    <section
      aria-labelledby="cleaner-photo-reqs-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-photo-reqs-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("cleaner:photoRequirements.title")}
      </h2>
      <ul
        aria-label={t("cleaner:photoRequirements.title")}
        className="flex flex-col gap-2"
      >
        {requirements.data.map((entry) => {
          const covered = entry.uploaded;
          return (
            <li
              key={entry.photoType}
              className="flex min-w-0 items-start justify-between gap-3 rounded-md border bg-background p-3"
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium text-foreground">
                  {entry.label}
                  {entry.required ? (
                    <span className="ml-2 text-xs font-medium text-destructive">
                      {t("cleaner:photoRequirements.required")}
                    </span>
                  ) : null}
                </span>
                <span
                  className={
                    covered
                      ? "text-xs text-state-success-text"
                      : "text-xs text-state-warning-text"
                  }
                >
                  {covered
                    ? t("cleaner:photoRequirements.covered")
                    : t("cleaner:photoRequirements.pending")}
                </span>
              </div>
              {/* Only mount the upload control when the task is in a state
                  that admits uploads (R5.1). The `uploaded: true` branch
                  never offers a button — covered is covered (D17). */}
              {!covered && canUpload && renderUpload ? (
                renderUpload(entry)
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}