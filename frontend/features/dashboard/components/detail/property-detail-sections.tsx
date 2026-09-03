"use client";

import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

import type { IncidentSeverity, PropertyDetail } from "../../data";
import { formatDate } from "../../lib/format";

/**
 * Presentational detail sections (PRD §9.2). Pure rendering of what the DTO
 * carries — no business logic. Photos use the backend-provided signed URL as-is;
 * no storage URL is ever constructed client-side (security.md rule 5).
 */
function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-2 p-4">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <div className="text-sm text-muted-foreground">{children}</div>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span>{label}</span>
      <span className="text-right font-medium text-foreground">{value}</span>
    </div>
  );
}

export function PropertyDetailSections({ detail }: { detail: PropertyDetail }) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const reservation = detail.currentOrNextReservation;

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Section title={t("detail.reservation")}>
        {reservation ? (
          <div className="flex flex-col gap-1">
            <Row
              label={t("card.reservation")}
              value={reservation.reference ?? t("card.noReservation")}
            />
            <Row label={t("card.checkIn")} value={formatDate(reservation.checkIn, locale)} />
            <Row
              label={t("card.checkOut")}
              value={formatDate(reservation.checkOut, locale)}
            />
          </div>
        ) : (
          t("card.noReservation")
        )}
      </Section>

      <Section title={t("detail.guest")}>
        {detail.guest?.name ?? t("card.noGuest")}
      </Section>

      <Section title={t("detail.access")}>
        {detail.access?.label ?? t("detail.noAccess")}
      </Section>

      <Section title={t("detail.cleaning")}>
        {detail.cleaningStatus ?? t("detail.noCleaning")}
      </Section>

      <Section title={t("detail.incidents")}>
        {detail.openIncidents.length === 0 ? (
          t("detail.noIncidents")
        ) : (
          <ul className="flex flex-col gap-1">
            {detail.openIncidents.map((incident) => (
              <li key={incident.id} className="flex items-center gap-2">
                <Badge variant="secondary">
                  {t(`incident.severity.${incident.severity as IncidentSeverity}`)}
                </Badge>
                <span className="text-foreground">{incident.title}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("detail.financial")}>
        {detail.financial ? (
          <div className="flex flex-col gap-1">
            <Row
              label={t("financial.reservationTotal")}
              value={
                detail.financial.reservationTotal !== null
                  ? `${detail.financial.reservationTotal} ${detail.financial.currency}`
                  : "—"
              }
            />
            <Row
              label={t("financial.pendingExpenses")}
              value={
                detail.financial.pendingExpenses !== null
                  ? `${detail.financial.pendingExpenses} ${detail.financial.currency}`
                  : "—"
              }
            />
          </div>
        ) : (
          "—"
        )}
      </Section>

      <Section title={t("detail.approvals")}>
        {detail.pendingApprovals.length === 0 ? (
          t("detail.noApprovals")
        ) : (
          <ul className="flex flex-col gap-1">
            {detail.pendingApprovals.map((approval) => (
              <li key={approval.id} className="flex items-baseline justify-between gap-3">
                <span className="text-foreground">{approval.label}</span>
                {approval.amount !== null ? (
                  <span className="font-medium text-foreground">
                    {approval.amount} {approval.currency}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("detail.notes")}>
        {detail.notes ?? t("detail.noNotes")}
      </Section>

      <Section title={t("detail.photos")}>
        {detail.lastCleaningPhotos.length === 0 ? (
          t("detail.noPhotos")
        ) : (
          <div className="flex flex-wrap gap-2">
            {detail.lastCleaningPhotos.map((photo) => (
              // eslint-disable-next-line @next/next/no-img-element -- signed URL from backend; no next/image loader for external signed URLs
              <img
                key={photo.id}
                src={photo.url}
                alt={t("detail.photoAlt")}
                className="h-20 w-20 rounded-md object-cover"
              />
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
