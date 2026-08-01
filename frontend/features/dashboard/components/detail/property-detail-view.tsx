"use client";

import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { usePropertyDetail } from "../../hooks/use-dashboard-data";
import { PropertyDetailSections } from "./property-detail-sections";
import { PropertyTimeline } from "./property-timeline";

/**
 * Client view for `/properties/[id]` (PRD §9.2). Composes the property timeline
 * and the detail sections, and owns the loading / not-found / error states. A
 * §23 404 renders a localized "not found" (not a raw error); any other failure
 * renders the error convention with retry. Never exposes raw error detail.
 */
export function PropertyDetailView({ propertyId }: { propertyId: string }) {
  const { t } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const query = usePropertyDetail(propertyId);

  if (query.isPending) {
    return <LoadingState label={tStates("loading.label")} />;
  }

  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return (
        <EmptyState
          title={t("detail.notFound.title")}
          description={t("detail.notFound.description")}
        />
      );
    }
    return (
      <ErrorState
        title={t("cards.error.title")}
        description={t("cards.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  const detail = query.data;

  return (
    <div className="flex flex-col gap-6 p-4">
      <h1 className="text-lg font-semibold text-foreground">
        {detail.propertyCode}
      </h1>
      <PropertyDetailSections detail={detail} />
      <PropertyTimeline propertyId={propertyId} />
    </div>
  );
}
