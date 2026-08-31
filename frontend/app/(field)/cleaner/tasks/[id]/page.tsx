import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { CleanerTaskDetailView } from "@/features/cleaner";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("cleaner-task");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CleanerTaskDetailView taskId={id} />;
}