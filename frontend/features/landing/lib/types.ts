/**
 * Local prop shapes for the landing feature components (design D9).
 *
 * These describe the data each section consumes from the landing catalogue —
 * no business types live here. Keeping them local keeps the feature self-
 * contained: the route registry and shell metadata pass i18n keys around, the
 * components resolve them against the `landing` namespace.
 */

/** Lucide icon names the landing feature resolves (subset of the shell union). */
export type LandingIconName =
  | "CalendarCheck"
  | "Sparkles"
  | "ShieldAlert"
  | "BarChart3";

/** A single feature card in the four-up grid. */
export interface FeatureCardData {
  /** Lucide icon name (kept serializable, like the shell). */
  icon: LandingIconName;
  /** Translation key under `landing:features.<id>.title`. */
  titleKey: string;
  /** Translation key under `landing:features.<id>.body`. */
  bodyKey: string;
}

/** A footer column with a list of labelled links. */
export interface FooterColumn {
  /** Translation key prefix under `landing:footer.<id>`. */
  columnKey: string;
  /** Localised column heading key. */
  headingKey: string;
  /** Pre-resolved links (label key + href). */
  links: readonly { labelKey: string; href: string }[];
}

/** A pair of stat lines for the band — keyed, never hardcoded. */
export interface StatsBandProps {
  line1Key: string;
  line2Key: string;
}

/** Final CTA — title, button label and the href the button resolves to. */
export interface FinalCtaProps {
  titleKey: string;
  buttonLabelKey: string;
  buttonHrefKey: string;
}
