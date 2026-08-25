"use client";

import Link from "next/link";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { useReservations } from "../../hooks/use-reservations";
import { mapReservationsError } from "../../lib/error-mapping";
import type {
  ReservationFilters,
  ReservationList,
  ReservationSummaryDto,
} from "../../data";
import { ReservationsFilters } from "./reservations-filters";

/**
 * Client view for `/reservations` (proposal R2, design D5). It owns the
 * filters state, calls `useReservations(filters)`, pipes the result through
 * the error mapper, and renders one of the cross-cutting states or the table.
 *
 * The table is 6 columns (guest, property, stay, status, channel, amount) in
 * the v1 order (D5). The detail page reads the rest. The 404 variant is NOT
 * rendered in the list — a 404 over a list endpoint is treated as a generic
 * error (R3.5).
 *
 * Row navigation (D5): the entire row is clickable via a single `<Link>` that
 * wraps the guest/route text in the first cell; the link's `::after`
 * pseudo-element stretches over the row to give the user a wide hit area.
 * The link's accessible name is the localized "open reservation" copy, so
 * screen readers hear the destination, not the bare id (a11y). Wrapping the
 * `<tr>` directly in `<Link>` would produce invalid HTML — `<a>` cannot
 * legally contain `<tr>` — so the overlay pattern is the standard and
 * accessible alternative.
 */
export function ReservationsView() {
  const { t } = useTranslation("reservations");
  const { t: tNav } = useTranslation("navigation");
  const { t: tStates } = useTranslation("states");
  const [filters, setFilters] = useState<ReservationFilters>({});
  const query = useReservations(filters);
  const state = mapReservationsError<ReservationList>(query);

  if (state.kind === "loading") {
    return <LoadingState label={tStates("loading.label")} />;
  }
  if (state.kind === "forbidden") {
    return <p role="alert">{t("fields.forbidden")}</p>;
  }
  if (state.kind === "validation") {
    return <p role="alert">{t("fields.validation")}</p>;
  }
  if (state.kind === "not-found") {
    // A 404 on the list endpoint is treated as a generic error (R3.5): the
    // list endpoint should never 404, so the only sensible state is the same
    // error panel the list shows for any other 5xx / network failure. The
    // `notFound` copy from the locale is reserved for the detail view.
    return (
      <ErrorState
        title={tStates("error.title")}
        description={tStates("error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={tStates("error.retry")}
      />
    );
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

  // state.kind === "ok" — `mapReservationsError<ReservationList>` propagates
  // the DTO type, so the cast is gone (was Finding F10 of the review).
  const page = state.data;

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-xl font-semibold text-foreground">
        {tNav("routes.reservations.title")}
      </h1>
      <ReservationsFilters value={filters} onChange={setFilters} />
      {page.data.length === 0 ? (
        // Empty state is rendered under the same page header so the screen
        // never loses its title (was Finding F13 of the review).
        <EmptyState
          title={tStates("empty.title")}
          description={tStates("empty.description")}
        />
      ) : (
        <>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className="border-b px-2 py-1 text-left">{t("fields.guest")}</th>
                <th className="border-b px-2 py-1 text-left">
                  {t("fields.property")}
                </th>
                <th className="border-b px-2 py-1 text-left">{t("fields.stay")}</th>
                <th className="border-b px-2 py-1 text-left">
                  {t("fields.status")}
                </th>
                <th className="border-b px-2 py-1 text-left">
                  {t("fields.channel")}
                </th>
                <th className="border-b px-2 py-1 text-left">
                  {t("fields.amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {page.data.map((row) => (
                <ReservationRow key={row.id} row={row} />
              ))}
            </tbody>
          </table>
          <Pagination
            page={page.page}
            totalPages={page.totalPages}
            onPrev={() =>
              setFilters((current) => ({
                ...current,
                page: (current.page ?? 1) - 1,
              }))
            }
            onNext={() =>
              setFilters((current) => ({
                ...current,
                page: (current.page ?? 1) + 1,
              }))
            }
          />
        </>
      )}
    </div>
  );
}

function ReservationRow({ row }: { row: ReservationSummaryDto }) {
  const { t } = useTranslation("reservations");
  const href = `/reservations/${row.id}`;
  return (
    <tr className="relative">
      <td className="border-b px-2 py-1">
        <Link
          href={href}
          aria-label={t("fields.openReservation")}
          className="text-primary underline after:absolute after:inset-0 after:content-['']"
        >
          {row.guestId ?? "—"}
        </Link>
      </td>
      <td className="border-b px-2 py-1">{row.propertyId}</td>
      <td className="border-b px-2 py-1">
        {row.checkInDate} → {row.checkOutDate}
      </td>
      <td className="border-b px-2 py-1">{t(`status.${row.status}`)}</td>
      <td className="border-b px-2 py-1">{row.channel}</td>
      <td className="border-b px-2 py-1">
        {row.grossAmount !== null
          ? `${row.grossAmount} ${row.currency}`
          : "—"}
      </td>
    </tr>
  );
}

function Pagination({
  page,
  totalPages,
  onPrev,
  onNext,
}: {
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  const { t } = useTranslation("reservations");
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className="rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
        disabled={page <= 1}
        onClick={onPrev}
        aria-label={t("fields.prevPage")}
      >
        {t("fields.prevPage")}
      </button>
      <button
        type="button"
        className="rounded-md border bg-background px-3 py-1 text-sm disabled:opacity-50"
        disabled={page >= totalPages}
        onClick={onNext}
        aria-label={t("fields.nextPage")}
      >
        {t("fields.nextPage")}
      </button>
    </div>
  );
}
