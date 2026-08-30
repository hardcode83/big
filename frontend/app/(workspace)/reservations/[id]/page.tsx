import type { Metadata } from "next";

import { ReservationDetailView } from "@/features/reservations";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("reservation-detail");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ReservationDetailView reservationId={id} />;
}
