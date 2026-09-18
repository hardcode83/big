"use client";

import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth";

import type { IncidentPhotoDto, IncidentPhotoStage } from "../../data";
import { useIncidentPhotos } from "../../hooks/use-incidents";
import { incidentsKeys } from "../../hooks/query-keys";

const STAGES: readonly IncidentPhotoStage[] = ["BEFORE", "AFTER"];

/**
 * The incident's photos on the manager's detail page (R1.1-R1.7, design D1/D2).
 *
 * Mirrors `TechPhotoGallery` (`features/tech/components/detail/tech-photo-gallery.tsx`)
 * closely: the same fixed `STAGES` grouping, the shared `LoadingState`/
 * `ErrorState`/`EmptyState`, and the same re-fetch-at-most-once-per-photo-id
 * recovery on a stale signed URL (R1.6). Unlike that precedent, this block
 * offers no upload control at all — uploading is the technician's job
 * (EXECUTE_INCIDENTS, a permission this manager-facing view does not have)
 * and there is no delete endpoint (R1.5).
 *
 * Each `url` is painted **verbatim** into the `<img src>` — never
 * transformed or concatenated to an origin of this app's own (R1.4).
 */
export function IncidentPhotosBlock({ incidentId }: { incidentId: string }) {
  const { t } = useTranslation("incidents");
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const retried = useRef<Set<string>>(new Set());
  const query = useIncidentPhotos(incidentId);

  const onImageError = (photoId: string) => {
    if (retried.current.has(photoId) || !user || user.tenant_id === null) {
      return;
    }
    retried.current.add(photoId);
    void queryClient.invalidateQueries({
      queryKey: incidentsKeys.photos(user.tenant_id, incidentId),
    });
  };

  const photos: IncidentPhotoDto[] = query.data ?? [];

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
        STAGES.map((stage) => {
          const ofStage = photos.filter((photo) => photo.stage === stage);
          if (ofStage.length === 0) return null;
          return (
            <div key={stage} className="flex flex-col gap-2">
              <h3 className="text-body-base text-muted-foreground">
                {t(`photos.stage.${stage}`)}
              </h3>
              <ul className="grid grid-cols-2 gap-2">
                {ofStage.map((photo) => (
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
          );
        })
      )}
    </section>
  );
}
