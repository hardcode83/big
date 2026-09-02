"use client";

import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/states";
import { useQueryClient } from "@tanstack/react-query";

import type { CleaningPhoto } from "../../data";
import { cleanerKeys } from "../../hooks/query-keys";

/**
 * The gallery block (R2.5). Renders one `<img>` per photo with the signed URL
 * the backend minted for this response — verbatim, no `next/image`, no
 * rewriting (D10).
 *
 * `eslint-disable-next-line @next/next/no-img-element` is the same comment
 * `features/tech/components/detail/photo-gallery.tsx` uses, for the same
 * reason — `next/image` would demand a `remotePatterns` declaration that we
 * do not own per tenant.
 *
 * Each `<img>` has its own `onError` that invalidates `cleanerKeys.photos` at
 * most **once** per photo id, tracked with a `useRef<Set<string>>`. A photo
 * that fails for a non-stale-signature reason stays broken after that single
 * retry — preferred over a loop that asks the backend to re-list endlessly.
 */
export interface CleanerTaskPhotoGalleryProps {
  tenantId: string;
  taskId: string;
  photos: CleaningPhoto[];
}

export function CleanerTaskPhotoGallery({
  tenantId,
  taskId,
  photos,
}: CleanerTaskPhotoGalleryProps) {
  const { t } = useTranslation(["cleaner", "states"]);
  const queryClient = useQueryClient();
  const retriedRef = useRef<Set<string>>(new Set());

  function handlePhotoError(photoId: string) {
    if (retriedRef.current.has(photoId)) {
      return;
    }
    retriedRef.current.add(photoId);
    void queryClient.invalidateQueries({
      queryKey: cleanerKeys.photos(tenantId, taskId),
    });
  }

  if (photos.length === 0) {
    return (
      <section
        aria-labelledby="cleaner-gallery-heading"
        className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
      >
        <h2
          id="cleaner-gallery-heading"
          className="text-sm font-semibold text-foreground"
        >
          {t("cleaner:gallery.title")}
        </h2>
        <EmptyState
          title={t("cleaner:gallery.empty.title")}
          description={t("cleaner:gallery.empty.description")}
        />
      </section>
    );
  }

  return (
    <section
      aria-labelledby="cleaner-gallery-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-gallery-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("cleaner:gallery.title")}
      </h2>
      <ul
        aria-label={t("cleaner:gallery.title")}
        className="grid grid-cols-2 gap-3 sm:grid-cols-3"
      >
        {photos.map((photo) => (
          <li
            key={photo.id}
            className="overflow-hidden rounded-md border bg-background"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={photo.url}
              alt={t("cleaner:gallery.alt")}
              loading="lazy"
              onError={() => handlePhotoError(photo.id)}
              className="h-32 w-full object-cover"
            />
          </li>
        ))}
      </ul>
    </section>
  );
}