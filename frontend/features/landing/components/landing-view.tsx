import { FeaturesGrid } from "./features-grid";
import { FinalCta } from "./final-cta";
import { Hero } from "./hero";
import { LandingFooter } from "./landing-footer";
import { StatsBand } from "./stats-band";

/**
 * Root Server Component of the public landing at `/` (design D9). Composes
 * the five sections — Hero, FeaturesGrid (with `<section id="features">`
 * already wrapped by the grid so the marketing nav's `#features` anchor
 * targets it), StatsBand, FinalCta, LandingFooter — in that order.
 *
 * Pure server render: every section resolves its copy from the `landing`
 * catalogue via `getServerT()`, no client JS lands in the page beyond what
 * the `PublicShell` chrome already ships (the locale and theme switchers).
 */
export async function LandingView() {
  return (
    <>
      <Hero />
      <FeaturesGrid />
      <StatsBand />
      <FinalCta />
      <LandingFooter />
    </>
  );
}
