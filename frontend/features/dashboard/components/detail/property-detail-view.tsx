"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { EditPropertyForm } from "@/features/properties";
import { useHasPermission } from "@/lib/auth";

import { usePropertyDetail } from "../../hooks/use-dashboard-data";
import { PropertyDetailSections } from "./property-detail-sections";
import { PropertyTimeline } from "./property-timeline";

/**
 * Client view for `/properties/[id]` (PRD §9.2). Composes the property timeline
 * and the detail sections, and owns the loading / not-found / error states. A
 * §23 404 renders a localized "not found" (not a raw error); any other failure
 * renders the error convention with retry. Never exposes raw error detail.
 *
 * It also hosts the write affordances for the property (proposal R2, design
 * D2/D3/D13): an "Edit" action, visible only with `MANAGE_PROPERTIES`, opening a
 * `Sheet` over `EditPropertyForm`. That form is imported across features from
 * `@/features/properties` and fetches the full property itself (design D7) —
 * `usePropertyDetail` below is the *dashboard aggregate*, a different endpoint
 * with a narrower shape that carries none of the writable fields, and the two
 * must not be conflated.
 *
 * The button copy lives in this view's own `dashboard` namespace (design D13);
 * the form's field labels come from `properties`.
 */
export function PropertyDetailView({ propertyId }: { propertyId: string }) {
  const { t } = useTranslation("dashboard");
  const { t: tStates } = useTranslation("states");
  const query = usePropertyDetail(propertyId);
  // Both hooks run before any early return (rules of hooks) — the loading and
  // error branches below return before the header ever renders.
  //
  // A UX courtesy only: the backend still answers `403` to a `PATCH` from
  // anyone lacking the permission («RBAC del backend decide, el frontend solo
  // oculta», `steering/frontend.md`).
  const canManageProperties = useHasPermission("MANAGE_PROPERTIES");
  const [isEditOpen, setIsEditOpen] = useState(false);

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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-headline-md font-semibold text-foreground">
          {detail.propertyCode}
        </h1>
        {/* The property's write actions. Section 5's "Retire property" button
            belongs in this same group, after "Edit". */}
        {canManageProperties ? (
          <div className="flex items-center gap-2">
            <Button type="button" onClick={() => setIsEditOpen(true)}>
              {t("detail.edit.button")}
            </Button>
          </div>
        ) : null}
      </div>
      <PropertyDetailSections detail={detail} />
      <PropertyTimeline propertyId={propertyId} />
      <Sheet open={isEditOpen} onOpenChange={setIsEditOpen}>
        <SheetContent closeLabel={t("detail.edit.close")}>
          <SheetHeader>
            <SheetTitle>{t("detail.edit.title")}</SheetTitle>
          </SheetHeader>
          <EditPropertyForm
            propertyId={propertyId}
            onCancel={() => setIsEditOpen(false)}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}
