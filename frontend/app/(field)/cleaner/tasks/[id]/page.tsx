import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { CleanerTaskDetailView } from "@/features/cleaner";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("cleaner-task");
}

interface PageProps {
  params: { id: string };
}

export default function Page({ params }: PageProps) {
  return <CleanerTaskDetailView taskId={params.id} />;
}