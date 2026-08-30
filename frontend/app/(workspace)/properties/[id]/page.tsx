import type { Metadata } from "next";

import { PropertyDetailView } from "@/features/dashboard";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  // Generic localized metadata — never interpolates the id (frontend-foundation).
  return routeMetadata("property-detail");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <PropertyDetailView propertyId={id} />;
}
