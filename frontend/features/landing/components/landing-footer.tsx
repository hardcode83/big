import { getServerT } from "@/lib/i18n/server";

/**
 * Landing footer (R3.3, design D8). Server Component.
 *
 * Renders the copyright line today. The three column arrays (`footer.product`,
 * `footer.company`, `footer.legal`) are `[]` — `Pricing`, `Portfolio`,
 * `Team` and `Sign Up` are deliberately NOT rendered because their pages
 * do not exist yet (R3.3). When a future entry adds a link, it goes into
 * the catalogue (`frontend/locales/{es,en}/landing.json`) and the columns
 * render automatically; this component stays as the layout anchor.
 */
export async function LandingFooter() {
  const t = await getServerT();

  return (
    <footer className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-6 border-t border-border pt-8 md:flex-row md:items-start md:justify-between">
        <p className="text-body-base text-muted-foreground">
          {t("landing:footer.copyright")}
        </p>
        {/* Columns render empty today; the catalogue reserves
          * `footer.product`, `footer.company` and `footer.legal` arrays
          * for future entries that do add destinations. */}
        <div data-empty-footer-columns aria-hidden="true" />
      </div>
    </footer>
  );
}
