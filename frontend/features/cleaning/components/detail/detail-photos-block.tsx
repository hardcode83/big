"use client";

import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth";

import type { CleaningPhotoDto } from "../../data";
import { useCleaningTaskPhotos } from "../../hooks/use-cleaning-photos";
import { cleaningKeys } from "../../hooks/query-keys";

/**
 * The cleaning task's photos (R2.1-R2.6, design D1/D4).
 *
 * Mirrors `TechPhotoGallery` (`features/tech/components/detail/tech-photo-gallery.tsx`)
 * closely: shared `LoadingState`/`ErrorState`/`EmptyState`, and the same
 * re-fetch-at-most-once-per-photo-id recovery on a stale signed URL (R2.5).
 * Two differences from that precedent:
 *
 * - Grouping is by `photoType`, a free-form `string` the task's checklist
 *   template defines (design D4) — not the fixed `STAGES` array incidents use.
 *   The group order is first-appearance order over the already-chronological
 *   list the API returns (`created_at, id`), never sorted alphabetically.
 * - No upload control: uploading is the cleaner's job
 *   (EXECUTE_CLEANING_TASKS, a permission this manager-facing view does not
 *   gate on and does not offer) and there is no delete endpoint (R2.4).
 *
 * Each `url` is painted **verbatim** into the `<img src>` — never
 * transformed or concatenated to an origin of this app's own (R2.3).
 */
export function DetailPhotosBlock({ taskId }: { taskId: string }) {
  const { t } = useTranslation("cleaning");
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const retried = useRef<Set<string>>(new Set());
  const query = useCleaningTaskPhotos(taskId);

  const onImageError = (photoId: string) => {
    if (retried.current.has(photoId) || !user || user.tenant_id === null) {
      return;
    }
    retried.current.add(photoId);
    void queryClient.invalidateQueries({
      queryKey: cleaningKeys.photos(user.tenant_id, taskId),
    });
  };

  const photos: CleaningPhotoDto[] = query.data ?? [];
  const groups = groupByPhotoType(photos);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-body-lg font-semibold text-foreground">
        {t("photos.title")}
      </h2>

      {query.isPending ? (
        <LoadingState label={t("photos.loading")} />
      ) : query.isError ? (
        <ErrorState
          title={t("photos.error.title")}
          description={t("photos.error.description")}
          retryLabel={t("photos.error.retry")}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : photos.length === 0 ? (
        <EmptyState
          title={t("photos.empty.title")}
          description={t("photos.empty.description")}
        />
      ) : (
        groups.map(([photoType, ofType]) => (
          <div key={photoType} className="flex flex-col gap-2">
            <h3 className="text-body-base text-muted-foreground">
              {photoType}
            </h3>
            <ul className="grid grid-cols-2 gap-2">
              {ofType.map((photo) => (
                <li key={photo.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={photo.url}
                    alt={t("photos.alt")}
                    className="w-full rounded-md border border-border object-cover"
                    onError={() => onImageError(photo.id)}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}

/**
 * Groups `photos` by `photoType` in first-appearance order (design D4): the
 * order of the returned tuples is the order each `photoType` value is first
 * seen in `photos`, which is itself already chronological (`created_at, id`)
 * from the API — never sorted alphabetically.
 */
function groupByPhotoType(
  photos: readonly CleaningPhotoDto[],
): Array<[string, CleaningPhotoDto[]]> {
  const order: string[] = [];
  const byType = new Map<string, CleaningPhotoDto[]>();
  for (const photo of photos) {
    const existing = byType.get(photo.photoType);
    if (existing) {
      existing.push(photo);
    } else {
      byType.set(photo.photoType, [photo]);
      order.push(photo.photoType);
    }
  }
  return order.map((photoType) => [photoType, byType.get(photoType)!]);
}
