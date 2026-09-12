import type { Metadata } from "next";

import { ReviewsView } from "@/features/reviews";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("reviews");
}

export default function Page() {
  return <ReviewsView />;
}