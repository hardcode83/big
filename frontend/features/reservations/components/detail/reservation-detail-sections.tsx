"use client";

import { useTranslation } from "react-i18next";

import type {
  GuestSummaryDto,
  PaymentStatus,
  ReservationAccessStatus,
  ReservationChannel,
  ReservationDetailDto,
  ReservationStatus,
} from "../../data";

/**
 * Pure presentational sub-components for the detail view. They receive the
 * already-mapped UI DTOs (camelCase) and only render; no fetching, no
 * state. The free-text fields (`internalNotes`, `specialRequests`) are
 * rendered with plain `{value}` — never `dangerouslySetInnerHTML` — per R3.3.
 *
 * Every visible label is read from the `reservations` i18n namespace; the
 * module carries no UI strings (R5.2 / steering/frontend.md). Typed props
 * keep the contract honest — `paymentStatus` is the `PaymentStatus` enum, not
 * an unconstrained `string`, so a future enum change is caught at the
 * component boundary.
 */

export function DetailHeader({
  id,
  status,
  channel,
}: {
  id: string;
  status: ReservationStatus;
  channel: ReservationChannel;
}) {
  const { t } = useTranslation("reservations");
  return (
    <header className="flex flex-wrap items-baseline gap-2">
      <span className="font-mono text-xs text-muted-foreground">{id}</span>
      <span className="text-sm font-medium">{t(`status.${status}`)}</span>
      <span className="text-xs text-muted-foreground">{channel}</span>
    </header>
  );
}

export function DetailPropertyBlock({
  propertyInternalCode,
  propertyName,
}: {
  propertyInternalCode: string | null;
  propertyName: string | null;
}) {
  const { t } = useTranslation("reservations");
  return (
    <section aria-label={t("fields.property")}>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.propertyCode")}</dt>
          <dd>{propertyInternalCode ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.propertyName")}</dt>
          <dd>{propertyName ?? "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DetailStayBlock({
  checkInDate,
  checkOutDate,
  nights,
}: {
  checkInDate: string;
  checkOutDate: string;
  nights: number;
}) {
  const { t } = useTranslation("reservations");
  return (
    <section aria-label={t("fields.stay")}>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.checkIn")}</dt>
          <dd>{checkInDate}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.checkOut")}</dt>
          <dd>{checkOutDate}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.nights")}</dt>
          <dd>{nights}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DetailPartyBlock({
  adults,
  childrenCount,
  totalGuests,
}: {
  adults: number;
  childrenCount: number;
  totalGuests: number;
}) {
  const { t } = useTranslation("reservations");
  return (
    <section aria-label={t("fields.totalGuests")}>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.adults")}</dt>
          <dd>{adults}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.children")}</dt>
          <dd>{childrenCount}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.totalGuests")}</dt>
          <dd>{totalGuests}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DetailFinancialBlock({
  grossAmount,
  netAmount,
  otaCommission,
  currency,
}: {
  grossAmount: string | null;
  netAmount: string | null;
  otaCommission: string | null;
  currency: string;
}) {
  const { t } = useTranslation("reservations");
  return (
    <section aria-label={t("fields.amount")}>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.gross")}</dt>
          <dd>
            {grossAmount !== null
              ? `${grossAmount} ${currency}`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.net")}</dt>
          <dd>
            {netAmount !== null
              ? `${netAmount} ${currency}`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.ota")}</dt>
          <dd>
            {otaCommission !== null
              ? `${otaCommission} ${currency}`
              : "—"}
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function DetailPaymentBlock({
  paymentStatus,
  accessStatus,
  cleaningRequired,
}: {
  paymentStatus: PaymentStatus;
  accessStatus: ReservationAccessStatus | null;
  cleaningRequired: boolean;
}) {
  const { t } = useTranslation("reservations");
  return (
    <section aria-label={t("fields.paymentStatus")}>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.paymentStatus")}</dt>
          <dd>{paymentStatus}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.accessStatus")}</dt>
          <dd>{accessStatus ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.cleaningRequired")}</dt>
          <dd>{cleaningRequired ? t("fields.yes") : t("fields.no")}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DetailGuestBlock({ guest }: { guest: GuestSummaryDto | null }) {
  const { t } = useTranslation("reservations");
  if (!guest) {
    return (
      <section aria-label={t("fields.guestBlock")}>
        <p className="text-sm text-muted-foreground">{t("fields.guestEmpty")}</p>
      </section>
    );
  }
  return (
    <section aria-label={t("fields.guestBlock")}>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t("fields.fullName")}</dt>
          <dd>{guest.fullName}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.email")}</dt>
          <dd>{guest.email ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.phone")}</dt>
          <dd>{guest.phone ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("fields.preferredLanguage")}</dt>
          <dd>{guest.preferredLanguage}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DetailNotesBlock({
  internalNotes,
  specialRequests,
}: {
  internalNotes: string | null;
  specialRequests: string | null;
}) {
  const { t } = useTranslation("reservations");
  if (!internalNotes && !specialRequests) {
    return null;
  }
  return (
    <section className="flex flex-col gap-2">
      {internalNotes ? (
        <div>
          <h3 className="text-sm font-medium">
            {t("fields.internalNotes")}
          </h3>
          <p className="text-sm">{internalNotes}</p>
        </div>
      ) : null}
      {specialRequests ? (
        <div>
          <h3 className="text-sm font-medium">
            {t("fields.specialRequests")}
          </h3>
          <p className="text-sm">{specialRequests}</p>
        </div>
      ) : null}
    </section>
  );
}

export function composeDetailSections(detail: ReservationDetailDto) {
  return {
    header: <DetailHeader id={detail.id} status={detail.status} channel={detail.channel} />,
    property: (
      <DetailPropertyBlock
        propertyInternalCode={detail.propertyInternalCode}
        propertyName={detail.propertyName}
      />
    ),
    stay: (
      <DetailStayBlock
        checkInDate={detail.checkInDate}
        checkOutDate={detail.checkOutDate}
        nights={detail.nights}
      />
    ),
    party: (
      <DetailPartyBlock
        adults={detail.adults}
        childrenCount={detail.children}
        totalGuests={detail.totalGuests}
      />
    ),
    financial: (
      <DetailFinancialBlock
        grossAmount={detail.grossAmount}
        netAmount={detail.netAmount}
        otaCommission={detail.otaCommission}
        currency={detail.currency}
      />
    ),
    payment: (
      <DetailPaymentBlock
        paymentStatus={detail.paymentStatus}
        accessStatus={detail.accessStatus}
        cleaningRequired={detail.cleaningRequired}
      />
    ),
    guest: <DetailGuestBlock guest={detail.guest} />,
    notes: (
      <DetailNotesBlock
        internalNotes={detail.internalNotes}
        specialRequests={detail.specialRequests}
      />
    ),
  };
}
