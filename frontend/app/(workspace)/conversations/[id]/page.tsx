import type { Metadata } from "next";

import { ConversationThreadView } from "@/features/conversations";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("conversation-detail");
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ConversationThreadView conversationId={id} />;
}