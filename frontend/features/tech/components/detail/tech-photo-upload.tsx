"use client";

import { useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  useUploadIncidentPhoto,
  type IncidentPhotoStage,
} from "@/features/incidents";

const STAGES: readonly IncidentPhotoStage[] = ["BEFORE", "AFTER"];

/**
 * Upload one photo, offered **only** in `IN_PROGRESS` and
 * `WAITING_EXTERNAL_PARTS` (R5.3, design D11).
 *
 * There is **no** client-side check of size or format. `accept` and `capture`
 * are picker hints, not validation: the backend decides the format by reading
 * the bytes and never consults the `Content-Type` the client sends, and the
 * size cap is a backend environment variable published in no contract, so
 * copying it here would invent a number that can differ from the real one. The
 * `413` and the `422` are the boundary, exactly as the server's `now` is for
 * the ETA.
 *
 * Four distinct messages and no automatic retry (R5.6). The `422` names the
 * accepted formats because its frequent cause on a phone is an iPhone HEIC, and
 * what fixes that is changing the format, not trying again.
 *
 * The `409` message deliberately names **no** reason. The upload invalidates
 * the incident on a 409 (design D8), so the refreshed status arrives and this
 * form withdraws — R5.3 only offers it in `IN_PROGRESS` and
 * `WAITING_EXTERNAL_PARTS` — while the action bar explains what the incident
 * became. A reason rendered here could only ever be `out-of-order`: by the time
 * the status is `RESOLVED`, `CANCELLED` or `AWAITING_OWNER_APPROVAL` this
 * component no longer exists to say so.
 */
export function TechPhotoUpload({ incidentId }: { incidentId: string }) {
  const { t } = useTranslation("tech");
  const [stage, setStage] = useState<IncidentPhotoStage>("BEFORE");
  const fileInput = useRef<HTMLInputElement>(null);
  const upload = useUploadIncidentPhoto();

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    upload.mutate({ incidentId, file, stage });
  };

  const errorMessage = (): string | undefined => {
    const error = upload.error;
    if (!error) return undefined;
    if (!(error instanceof ApiError)) return t("upload.errors.generic");
    switch (error.status) {
      case 409:
        return t("upload.errors.conflict");
      case 413:
        return t("upload.errors.tooLarge");
      case 422:
        return t("upload.errors.unsupportedFormat");
      case 502:
        return t("upload.errors.storage");
      default:
        return t("upload.errors.generic");
    }
  };

  const message = errorMessage();

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2 className="text-base font-semibold text-foreground">
        {t("upload.title")}
      </h2>
      <p className="text-xs text-muted-foreground">{t("upload.optional")}</p>

      <div className="flex flex-col gap-1">
        <label htmlFor="tech-photo" className="text-sm text-muted-foreground">
          {t("upload.file")}
        </label>
        <input
          id="tech-photo"
          ref={fileInput}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          className="min-h-11 rounded-md border bg-background px-3 py-2 text-sm"
        />
      </div>

      <fieldset className="flex flex-col gap-1">
        <legend className="text-sm text-muted-foreground">
          {t("upload.stage")}
        </legend>
        <div className="flex gap-2">
          {STAGES.map((option) => (
            <label
              key={option}
              className="flex min-h-11 items-center gap-2 text-sm"
            >
              <input
                type="radio"
                name="stage"
                value={option}
                checked={stage === option}
                onChange={() => setStage(option)}
              />
              {t(`photos.stage.${option}`)}
            </label>
          ))}
        </div>
      </fieldset>

      {message ? (
        <p role="alert" className="text-sm text-state-error-text">
          {message}
        </p>
      ) : null}

      <Button type="submit" className="min-h-11" disabled={upload.isPending}>
        {upload.isPending ? t("upload.uploading") : t("upload.submit")}
      </Button>
    </form>
  );
}
