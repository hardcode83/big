import type { Metadata } from "next";

import { IncidentDetailView } from "@/features/incidents";
import { routeMetadata } from "@/features/shell";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("incident-detail");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <IncidentDetailView incidentId={id} />;
}