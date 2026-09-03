"use client";

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { PhotoRequirementState } from "../../data";
import { useUploadCleaningPhoto } from "../../hooks/use-cleaner-cycle";
import { mapCleanerError } from "../../lib/error-mapping";

/**
 * One per-category photo-upload control (R5.1, R5.2, R5.3, R5.5).
 *
 * Renders a button. On click:
 *
 * - Opens a native `<input type="file" accept="image/jpeg,image/png,image/webp"
 *   capture="environment">`. The `accept` is a **hint**, not validation —
 *   `cleaning.md` §Fotos de la limpieza fixes the format from the file's
 *   bytes (R5.5).
 * - Arms a `FormData` with `photo_type` taken from the entry the user touched
 *   (R5.3) — not from a free text field — plus `file`.
 * - Fires `useUploadCleaningPhoto` (D9).
 *
 * The button is mounted only when `task.status === 'IN_PROGRESS'` (R5.1).
 * Error mapping (R5.5):
 * - `409` → surface a localized message via `mapCleanerError`. The reason is
 *   not enumerated here — `conflictReason` reads it from the refreshed task
 *   (D7, R7.3); the view orchestrates that on the close mutation, not here.
 * - `413` → "demasiado grande".
 * - `422` → the message names JPEG/PNG/WebP (R5.5).
 * - `502` → "almacenamiento no disponible".
 *
 * No automatic retry on any of the four (R5.5).
 */
export interface CleanerTaskPhotoUploadButtonProps {
  taskId: string;
  entry: PhotoRequirementState;
}

export function CleanerTaskPhotoUploadButton({
  taskId,
  entry,
}: CleanerTaskPhotoUploadButtonProps) {
  const { t } = useTranslation("cleaner");
  const inputRef = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const mutation = useUploadCleaningPhoto();

  function onButtonClick() {
    setLocalError(null);
    inputRef.current?.click();
  }

  function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    // The `photo_type` travels **from the entry the cleaner touched**, never
    // from the file's name or any free input (R5.3).
    mutation.mutate(
      { taskId, photoType: entry.photoType, file },
      {
        onError: (error) => {
          const map = mapCleanerError(error, "uploadPhoto");
          setLocalError(map.messageKey);
        },
        onSettled: () => {
          // Reset the input so picking the same file again triggers `change`.
          if (inputRef.current) {
            inputRef.current.value = "";
          }
        },
      },
    );
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        onChange={onFileChange}
        className="sr-only"
        aria-hidden
      />
      <Button
        type="button"
        variant="outline"
        className="tap-target"
        onClick={onButtonClick}
        disabled={mutation.isPending}
      >
        {mutation.isPending
          ? t("upload.uploading")
          : t("photoRequirements.upload")}
      </Button>
      {localError ? (
        <span role="alert" className="max-w-[12rem] text-right text-xs text-destructive">
          {t(localError)}
        </span>
      ) : null}
    </div>
  );
}