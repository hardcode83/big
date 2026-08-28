"use client";

import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/lib/auth";
import {
  incidentsKeys,
  useIncidentPhotos,
  type IncidentPhotoDto,
  type IncidentPhotoStage,
} from "@/features/incidents";

const STAGES: readonly IncidentPhotoStage[] = ["BEFORE", "AFTER"];

/**
 * The incident's photos (R5.1, design D10).
 *
 * Each `url` is painted **verbatim** into the `src`. It works on both storage
 * backends without this screen knowing which is in play: the `LOCAL` URL is
 * relative and the browser resolves it against the page's origin, where the
 * `/api/` proxy lives; the `S3` one is absolute and presigned. Nothing is
 * persisted, rewritten or rebuilt, and there is no `storage_key` in the client
 * (R5.2).
 *
 * Recovery from an expired signature is **re-listing**: the image's `onError`
 * invalidates the photo list at most **once per mounted photo id**, so a photo
 * that is genuinely unreadable does not spin in a refetch loop.
 *
 * No deletion is offered — the API exposes none (R5.7).
 */
export function TechPhotoGallery({ incidentId }: { incidentId: string }) {
  const { t } = useTranslation("tech");
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const retried = useRef<Set<string>>(new Set());
  const query = useIncidentPhotos(incidentId);

  const onImageError = (photoId: string) => {
    if (retried.current.has(photoId) || !user) {
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
      <h2 className="text-base font-semibold text-foreground">
        {t("photos.title")}
      </h2>

      {query.isPending ? (
        <p className="text-sm text-muted-foreground">{t("photos.loading")}</p>
      ) : query.isError ? (
        <p role="alert" className="text-sm text-state-error-text">
          {t("photos.error")}
        </p>
      ) : photos.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("photos.empty")}</p>
      ) : (
        STAGES.map((stage) => {
          const ofStage = photos.filter((photo) => photo.stage === stage);
          if (ofStage.length === 0) return null;
          return (
            <div key={stage} className="flex flex-col gap-2">
              <h3 className="text-sm text-muted-foreground">
                {t(`photos.stage.${stage}`)}
              </h3>
              <ul className="grid grid-cols-2 gap-2">
                {ofStage.map((photo) => (
                  <li key={photo.id}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={photo.url}
                      alt={t("photos.alt")}
                      className="w-full rounded-md border object-cover"
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
