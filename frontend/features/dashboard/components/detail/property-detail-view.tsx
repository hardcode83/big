"use client";

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { EditPropertyForm, useProperty, useUpdateProperty } from "@/features/properties";
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
 * A "Retire property" action (proposal R2.6, design D9) sits next to Edit,
 * same `MANAGE_PROPERTIES` gate, plus an extra one: it only renders for a
 * property whose `status` is not already `INACTIVE`. `status` is not on
 * `usePropertyDetail`'s aggregate either, so this view calls `useProperty`
 * itself (the same hook `EditPropertyForm` uses) purely to read that one
 * field. Confirming in the `AlertDialog` calls `useUpdateProperty` with
 * exactly `{ status: "INACTIVE" }` — never merged with the edit form's
 * pending changes, which live in a wholly separate component instance.
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
  // Only used to read the property's current `status` for the retire gate
  // (design D9) — never rendered as its own loading/error state; if it has
  // not resolved yet (or fails), the retire button simply stays hidden.
  const propertyQuery = useProperty(propertyId);
  const retireMutation = useUpdateProperty();
  const [isRetireOpen, setIsRetireOpen] = useState(false);
  const retireSubmittingRef = useRef(false);

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
  // Hidden unless the property's own detail has confirmed a non-"INACTIVE"
  // status (design D9) — `propertyQuery.data === undefined` (still loading,
  // or errored) resolves to hidden, not shown.
  const canRetire =
    canManageProperties &&
    propertyQuery.data !== undefined &&
    propertyQuery.data.status !== "INACTIVE";

  // `AlertDialogAction` is Radix's `Dialog.Close` under the hood, which closes
  // unconditionally unless the click handler calls `event.preventDefault()`
  // (same pattern as `ManagerIncidentActions`' `CancelDialog`) — this one does,
  // and only calls `setIsRetireOpen(false)` once the mutation actually
  // succeeds, so a failed retire keeps the dialog open with the error shown.
  function handleRetireConfirm(event: { preventDefault: () => void }) {
    event.preventDefault();
    if (retireSubmittingRef.current) {
      return;
    }
    retireSubmittingRef.current = true;
    retireMutation.mutate(
      { id: propertyId, input: { status: "INACTIVE" } },
      {
        onSuccess: () => setIsRetireOpen(false),
        onError: () => {
          // R2.6: the error renders beneath the confirm copy; the dialog stays
          // open so the user can retry or cancel.
        },
        onSettled: () => {
          retireSubmittingRef.current = false;
        },
      },
    );
  }

  return (
    <div className="flex flex-col gap-6 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-headline-md font-semibold text-foreground">
          {detail.propertyCode}
        </h1>
        {canManageProperties ? (
          <div className="flex items-center gap-2">
            <Button type="button" onClick={() => setIsEditOpen(true)}>
              {t("detail.edit.button")}
            </Button>
            {canRetire ? (
              <Button
                type="button"
                variant="destructive"
                onClick={() => setIsRetireOpen(true)}
              >
                {t("detail.retire.button")}
              </Button>
            ) : null}
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
      <AlertDialog open={isRetireOpen} onOpenChange={setIsRetireOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("detail.retire.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("detail.retire.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {retireMutation.isError ? (
            <p role="alert" className="text-sm text-state-error-text">
              {t("detail.retire.genericError")}
            </p>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={retireMutation.isPending}>
              {t("detail.retire.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRetireConfirm}
              disabled={retireMutation.isPending}
              aria-busy={retireMutation.isPending}
            >
              {retireMutation.isPending
                ? t("detail.retire.confirming")
                : t("detail.retire.confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
