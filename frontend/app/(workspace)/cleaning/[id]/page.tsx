import type { Metadata } from "next";

import { CleaningTaskDetailView } from "@/features/cleaning";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("cleaning-detail");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CleaningTaskDetailView taskId={id} />;
}