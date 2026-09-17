"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";

import type { CleaningTask } from "../../data";

/**
 * The "ir al contexto" row of `/cleaning/[id]` (proposal R4.1/R4.2/R4.3,
 * design D8).
 *
 * Three links, each gated exactly the way the proposal declares:
 *
 * - "Volver al listado" — `/cleaning`, always painted (R4.2, the only
 *   link that the navigation hierarchy requires regardless of role).
 * - "Ver vivienda" — `/properties/[property_id]`, only if the viewer has
 *   `READ_PROPERTIES` (R4.1). Manager and owner do, the operational roles
 *   do not (`lib/auth/permissions.ts` grants it to the two `workspace`
 *   roles only).
 * - "Ver reserva" — `/reservations/[reservation_id]`, only if the task has
 *   a `reservationId` AND the viewer has `READ_RESERVATIONS` (R4.3). When
 *   the role lacks the permission, the link is hidden — not degraded to
 *   plain text, because R3.2 already painted the code as data and we must
 *   not offer an affordance that would 403 the user.
 *
 * No `sticky` and no second header: the section sits at the bottom of the
 * article column, in line with the layout D8 names. The section is its own
 * `<nav>` so a screen reader announces it as navigation, not another data
 * block.
 */
export interface DetailContextLinksBlockProps {
  propertyId: CleaningTask["propertyId"];
  reservationId: CleaningTask["reservationId"];
  canReadProperties: boolean;
  canReadReservations: boolean;
}

export function DetailContextLinksBlock({
  propertyId,
  reservationId,
  canReadProperties,
  canReadReservations,
}: DetailContextLinksBlockProps) {
  const { t } = useTranslation("cleaning");
  return (
    <nav
      aria-label={t("detail.context.label")}
      className="flex flex-wrap gap-x-6 gap-y-2 pt-2"
    >
      <Link
        href="/cleaning"
        className="text-body-base text-primary underline-offset-4 hover:underline"
      >
        {t("detail.context.backToList")}
      </Link>
      {canReadProperties ? (
        <Link
          href={`/properties/${propertyId}`}
          className="text-body-base text-primary underline-offset-4 hover:underline"
        >
          {t("detail.context.viewProperty")}
        </Link>
      ) : null}
      {canReadReservations && reservationId !== null ? (
        <Link
          href={`/reservations/${reservationId}`}
          className="text-body-base text-primary underline-offset-4 hover:underline"
        >
          {t("detail.context.viewReservation")}
        </Link>
      ) : null}
    </nav>
  );
}