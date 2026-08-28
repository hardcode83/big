import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell";
import { TechIncidentDetailView } from "@/features/tech";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("tech-incident");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TechIncidentDetailView incidentId={id} />;
}
