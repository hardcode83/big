import type { Metadata } from "next";

import { ConversationsView } from "@/features/conversations";
import { routeMetadata } from "@/features/shell";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("conversations");
}

export default function Page() {
  return <ConversationsView />;
}