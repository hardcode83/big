import {
  BarChart3,
  CalendarCheck,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

import { getServerT } from "@/lib/i18n/server";
import type { FeatureCardData } from "../lib/types";

/**
 * Lucide icon resolver. Kept serializable in the data shape (icon NAME) and
 * resolved here, like the shell's `icon-map.ts`. Adding a new feature icon is
 * a one-line change — both sides of the resolution are local to the landing
 * feature.
 */
const ICONS = {
  CalendarCheck,
  Sparkles,
  ShieldAlert,
  BarChart3,
} as const;

export async function FeatureCard({ data }: { data: FeatureCardData }) {
  const t = await getServerT();
  const Icon = ICONS[data.icon];

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-6">
      <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Icon aria-hidden="true" className="h-5 w-5" />
      </div>
      <h3 className="text-headline-md font-semibold tracking-tight">
        {t(data.titleKey)}
      </h3>
      <p className="text-body-base text-muted-foreground">{t(data.bodyKey)}</p>
    </article>
  );
}
