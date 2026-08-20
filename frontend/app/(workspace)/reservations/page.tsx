import type { Metadata } from "next";

import { ReservationsView } from "@/features/reservations";
import { routeMetadata } from "@/features/shell";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("reservations");
}

export default function Page() {
  return <ReservationsView />;
}
