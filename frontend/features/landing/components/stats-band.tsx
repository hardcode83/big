import { getServerT } from "@/lib/i18n/server";

/**
 * Two-line stats band (R5.1, R5.2, design D6). Server Component.
 *
 * No numbers, no percentages — the maqueta's "500+ Propiedades gestionadas" /
 * "99% Satisfacción de propietarios" pair is rejected by `steering/product.md`
 * (two operational properties, multi-tenant SaaS is a future phase). The two
 * lines are PRODUCT statements — verifiable by the surrounding prose, not
 * invented metrics — and live in the landing catalogue.
 *
 * Rendered in the export's `text-data-mono` role (JetBrains Mono) so the band
 * lands on the maqueta's rhythm.
 */
export async function StatsBand() {
  const t = await getServerT();

  return (
    <section
      aria-label={t("landing:stats.line1")}
      className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 md:py-16 lg:px-8"
    >
      <div className="rounded-lg border border-border bg-surface/60 px-6 py-8 backdrop-blur">
        <p className="text-data-mono font-medium text-foreground">
          {t("landing:stats.line1")}
        </p>
        <p className="mt-3 text-data-mono font-medium text-muted-foreground">
          {t("landing:stats.line2")}
        </p>
      </div>
    </section>
  );
}
