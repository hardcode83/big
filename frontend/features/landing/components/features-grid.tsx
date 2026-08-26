import { getServerT } from "@/lib/i18n/server";
import type { FeatureCardData } from "../lib/types";
import { FeatureCard } from "./feature-card";

/**
 * The four-up features grid (R3.1, R3). Server Component composing four
 * `FeatureCard`s in a 1/2/4 column layout: 1 column mobile, 2 columns tablet,
 * 4 columns desktop. The `<section id="features">` wrapper is what the
 * marketing nav's `#features` anchor targets (D10).
 *
 * The feature set is the four the proposal names — Centralised Reservations,
 * Cleaning and Maintenance, Incident Control, Operational Analytics — with
 * their keys fixed against the landing catalogue.
 */
const FEATURES: readonly FeatureCardData[] = [
  {
    icon: "CalendarCheck",
    titleKey: "landing:features.reservations.title",
    bodyKey: "landing:features.reservations.body",
  },
  {
    icon: "Sparkles",
    titleKey: "landing:features.cleaning.title",
    bodyKey: "landing:features.cleaning.body",
  },
  {
    icon: "ShieldAlert",
    titleKey: "landing:features.incidents.title",
    bodyKey: "landing:features.incidents.body",
  },
  {
    icon: "BarChart3",
    titleKey: "landing:features.analytics.title",
    bodyKey: "landing:features.analytics.body",
  },
] as const;

export async function FeaturesGrid() {
  const t = await getServerT();

  return (
    <section
      id="features"
      aria-labelledby="features-heading"
      className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 md:py-24 lg:px-8"
    >
      <h2
        id="features-heading"
        className="text-headline-lg font-bold tracking-tight md:text-display-xl"
      >
        {t("navigation:routes.landing.title")}
      </h2>
      <div className="mt-8 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((feature) => (
          <FeatureCard key={feature.titleKey} data={feature} />
        ))}
      </div>
    </section>
  );
}
