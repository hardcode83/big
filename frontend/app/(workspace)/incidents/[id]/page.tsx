import type { Metadata } from "next";

import { ManagerIncidentDetailView } from "@/features/incidents";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("incident-detail");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ManagerIncidentDetailView incidentId={id} />;
}
