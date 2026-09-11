"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useHasPermission } from "@/lib/auth";

import { useCancelReservation, useReservation } from "../../hooks/use-reservations";
import { reservationMutationErrorKey } from "../../lib/mutation-error-mapping";
import { EditReservationForm } from "../edit/edit-reservation-form";
import { useState } from "react";
import { mapReservationsError } from "../../lib/error-mapping";
import type { ReservationDetailDto } from "../../data";
import {
  composeDetailSections,
} from "./reservation-detail-sections";

/**
 * Client view for `/reservations/[id]` (proposal R3, design D3). It pipes the
 * query through the error mapper and renders one of the cross-cutting states
 * or the composed detail sections.
 *
 * The `not-found` (404) variant IS rendered here, distinct from the list
 * (R3.5): a 404 on the detail endpoint is a legitimate "not found" — the
 * reservation is unknown to this tenant.
 */
export function ReservationDetailView({
  reservationId,
}: {
  reservationId: string;
}) {
  const { t } = useTranslation("reservations");
  const { t: tStates } = useTranslation("states");
  const { t: tNav } = useTranslation("navigation");
  const query = useReservation(reservationId);
  const canManage = useHasPermission("MANAGE_RESERVATIONS");
  const state = mapReservationsError<ReservationDetailDto>(query);

  if (state.kind === "loading") {
    return <LoadingState label={tStates("loading.label")} />;
  }
  if (state.kind === "forbidden") {
    return <p role="alert">{t("fields.forbidden")}</p>;
  }
  if (state.kind === "not-found") {
    return (
      <div className="flex flex-col gap-3 p-4">
        <Link
          href="/reservations"
          className="text-sm text-primary underline"
        >
          {`« ${t("fields.backToList")} »`}
        </Link>
        <EmptyState
          title={t("fields.notFound")}
          description=""
        />
      </div>
    );
  }
  if (state.kind === "validation") {
    return <p role="alert">{t("fields.validation")}</p>;
  }
  if (state.kind === "error") {
    return (
      <ErrorState
        title={tStates("error.title")}
        description={tStates("error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
  }

  // state.kind === "ok"
  const detail = state.data;
  const sections = composeDetailSections(detail);

  return (
    <div className="flex flex-col gap-4 p-4">
      <Link
        href="/reservations"
        className="text-sm text-primary underline"
      >
        {`« ${t("fields.backToList")} »`}
      </Link>
      <h1 className="text-xl font-semibold text-foreground">
        {tNav("routes.reservation-detail.title")}
      </h1>
      {sections.header}
      {sections.property}
      {sections.stay}
      {sections.party}
      {sections.guest}
      {sections.guestPortalLink}
      {sections.financial}
      {sections.payment}
      {sections.notes}
      {canManage ? (
        <ReservationManageActions detail={detail} />
      ) : null}
    </div>
  );
}

function ReservationManageActions({ detail }: { detail: ReservationDetailDto }) {
  const { t } = useTranslation("reservations");
  const cancel = useCancelReservation();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelAnnouncement, setCancelAnnouncement] = useState<string | null>(null);
  return <>
    <EditReservationForm detail={detail} />
    <Button variant="destructive" type="button" className="tap-target" onClick={() => setCancelOpen(true)} disabled={cancel.isPending}>{t("cancel.open")}</Button>
    <AlertDialog open={cancelOpen} onOpenChange={setCancelOpen}>
      <AlertDialogContent>
        <AlertDialogHeader><AlertDialogTitle>{t("cancel.title")}</AlertDialogTitle><AlertDialogDescription>{t("cancel.description")}</AlertDialogDescription></AlertDialogHeader>
        {cancel.isError ? <p role="alert">{t(reservationMutationErrorKey(cancel.error, "cancel"))}</p> : null}
        <AlertDialogFooter>
          <AlertDialogCancel>{t("cancel.keep")}</AlertDialogCancel>
          <AlertDialogAction disabled={cancel.isPending} aria-busy={cancel.isPending} onClick={(event) => { event.preventDefault(); cancel.mutate({ reservationId: detail.id }, { onSuccess: () => { setCancelOpen(false); setCancelAnnouncement(t("cancel.success")); } }); }}>
            {cancel.isPending ? t("cancel.submitting") : t("cancel.confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    {cancelAnnouncement ? <p role="status" aria-live="polite">{cancelAnnouncement}</p> : null}
  </>;
}
