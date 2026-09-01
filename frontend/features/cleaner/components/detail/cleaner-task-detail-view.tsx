"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth";

import {
  useCleanerTask,
  useCleanerTaskChecklist,
  useCleanerTaskContext,
  useCleanerTaskPhotoRequirements,
  useCleanerTaskPhotos,
} from "../../hooks/use-cleaner-tasks";
import { mapCleanerError } from "../../lib/error-mapping";
import { cleanerAcceptsChecklistItem } from "../../lib/cleaner-actions";
import { CleanerTaskActionBar } from "./cleaner-task-action-bar";
import { CleanerTaskChecklist } from "./cleaner-task-checklist";
import { CleanerTaskChecklistItem } from "./cleaner-task-checklist-item";
import { CleanerTaskContextBlock } from "./cleaner-task-context-block";
import { CleanerCompletionPanel } from "./cleaner-completion-panel";
import { CleanerTaskPhotoGallery } from "./cleaner-task-photo-gallery";
import { CleanerTaskPhotoRequirements } from "./cleaner-task-photo-requirements";
import { CleanerTaskPhotoUploadButton } from "./cleaner-task-photo-upload-button";

/**
 * The cleaner-app detail view (R2.1, R2.8, R7.2, R8.2, R8.3, design D4, D10,
 * D11, D12).
 *
 * Mounts `useCleanerTask`, `useCleanerTaskContext`, `useCleanerTaskChecklist`,
 * `useCleanerTaskPhotoRequirements`, `useCleanerTaskPhotos` in parallel.
 * Branches: `404` from any of them → `EmptyState` «tarea no disponible» with
 * «Volver a mis tareas»; loading → `LoadingState`; error → `ErrorState`
 * without retry on `4xx`.
 *
 * Composition: `ContextBlock` → `Checklist` → `PhotoRequirements` (with the
 * upload buttons inline) → `Gallery` → `ActionBar`. The completion panel
 * overlays the action bar only after a successful close.
 *
 * Renders inside `mx-auto w-full max-w-md p-4` to keep it mobile-first at 360
 * px (R8.3): no horizontal scroll.
 */
export interface CleanerTaskDetailViewProps {
  taskId: string;
}

export function CleanerTaskDetailView({ taskId }: CleanerTaskDetailViewProps) {
  const { t } = useTranslation(["cleaner", "states"]);
  const router = useRouter();
  const [hasClosed, setHasClosed] = useState(false);

  const { user } = useAuth();
  const tenantId = user?.tenant_id ?? "";

  const task = useCleanerTask(taskId);
  const context = useCleanerTaskContext(taskId);
  const checklist = useCleanerTaskChecklist(taskId);
  const requirements = useCleanerTaskPhotoRequirements(taskId);
  const photos = useCleanerTaskPhotos(taskId);

  const errorKind = pickErrorKind({
    hasTaskError: task.isError,
    hasContextError: context.isError,
    hasChecklistError: checklist.isError,
    hasRequirementsError: requirements.isError,
    hasPhotosError: photos.isError,
  });
  const firstError = pickFirstError([
    task.error,
    context.error,
    checklist.error,
    requirements.error,
    photos.error,
  ]);
  const errorMap =
    firstError && errorKind
      ? mapCleanerError(firstError, errorKind)
      : null;

  const isPending =
    task.isPending ||
    context.isPending ||
    checklist.isPending ||
    requirements.isPending ||
    photos.isPending;

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-md p-4">
        <LoadingState label={t("cleaner:detail.loading")} />
      </div>
    );
  }
  if (errorMap) {
    if (errorMap.state === "not-found") {
      return (
        <div className="mx-auto w-full max-w-md p-4">
          <EmptyState
            title={t(`cleaner:${errorMap.messageKey}`)}
            description={t("cleaner:detail.unavailable.description")}
            action={
              <Button
                type="button"
                onClick={() => router.replace("/cleaner")}
              >
                {t("cleaner:detail.back")}
              </Button>
            }
          />
        </div>
      );
    }
    return (
      <div className="mx-auto w-full max-w-md p-4">
        <ErrorState
          title={t(`cleaner:${errorMap.messageKey}`)}
          description={t("cleaner:detail.error.description")}
        />
      </div>
    );
  }
  if (
    !task.data ||
    !context.data ||
    !checklist.data ||
    !requirements.data
  ) {
    return (
      <div className="mx-auto w-full max-w-md p-4">
        <EmptyState
          title={t("cleaner:detail.unavailable.title")}
          description={t("cleaner:detail.unavailable.description")}
          action={
            <Button type="button" onClick={() => router.replace("/cleaner")}>
              {t("cleaner:detail.back")}
            </Button>
          }
        />
      </div>
    );
  }

  const taskData = task.data;
  const isInProgress = cleanerAcceptsChecklistItem(taskData.status);
  const canUploadPhotos = taskData.status === "IN_PROGRESS";

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 p-4">
      <CleanerTaskContextBlock task={taskData} context={context.data} />
      <CleanerTaskChecklist
        checklist={checklist.data}
        interactive={isInProgress}
        renderItemAction={(item) => (
          <CleanerTaskChecklistItem taskId={taskData.id} item={item} />
        )}
      />
      <CleanerTaskPhotoRequirements
        requirements={requirements.data}
        canUpload={canUploadPhotos}
        renderUpload={(entry) => (
          <CleanerTaskPhotoUploadButton
            taskId={taskData.id}
            entry={entry}
          />
        )}
      />
      <CleanerTaskPhotoGallery
        tenantId={tenantId}
        taskId={taskData.id}
        photos={photos.data ?? []}
      />
      <CleanerTaskActionBar
        task={taskData}
        checklist={checklist.data}
        requirements={requirements.data}
        onTaskCompleted={() => setHasClosed(true)}
      />
      {hasClosed ? <CleanerCompletionPanel /> : null}
    </div>
  );
}

function pickFirstError(
  errors: ReadonlyArray<Error | null>,
): Error | null {
  for (const err of errors) {
    if (err) return err;
  }
  return null;
}

function pickErrorKind(flags: {
  hasTaskError: boolean;
  hasContextError: boolean;
  hasChecklistError: boolean;
  hasRequirementsError: boolean;
  hasPhotosError: boolean;
}): "task" | "context" | "checklist" | "photoRequirements" | "photos" | null {
  if (flags.hasTaskError) return "task";
  if (flags.hasContextError) return "context";
  if (flags.hasChecklistError) return "checklist";
  if (flags.hasRequirementsError) return "photoRequirements";
  if (flags.hasPhotosError) return "photos";
  return null;
}