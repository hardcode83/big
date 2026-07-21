import type { Metadata } from "next";

import { createMetadataFromKeys } from "@/lib/metadata/create-route-metadata";
import { getRouteById } from "./route-registry";

/**
 * Resolves a route id to localized App Router metadata (design D19). The
 * registry lookup lives here in the shell feature; the generic i18n → Metadata
 * builder lives in `lib/metadata`, keeping the shared layer free of feature
 * imports (design D2).
 */
export function routeMetadata(routeId: string): Promise<Metadata> {
  const route = getRouteById(routeId);
  if (!route) {
    return createMetadataFromKeys(undefined);
  }
  return createMetadataFromKeys({
    titleKey: route.metadataTitleKey,
    descriptionKey: route.metadataDescriptionKey,
  });
}
