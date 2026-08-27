import { getServerT } from "@/lib/i18n/server";

/**
 * Hero of the landing page. Server Component, no client JS. Reads the
 * eyebrow, title and subtitle from the `landing` catalogue via the shared
 * `getServerT` server translator (design D7, D9).
 *
 * Typography uses the export's display roles — `text-display-2xl` on
 * desktop, `text-display-lg-mobile` below 768 px — so the headline lands on
 * the maqueta's rhythm without per-component CSS.
 */
export async function Hero() {
  const t = await getServerT();

  return (
    <section className="mx-auto w-full max-w-6xl px-4 pt-16 pb-12 sm:px-6 md:pt-24 md:pb-16 lg:px-8">
      <p className="text-label-caps uppercase text-primary">
        {t("landing:hero.eyebrow")}
      </p>
      <h1 className="mt-4 text-display-lg-mobile font-extrabold tracking-tight md:text-display-2xl">
        {t("landing:hero.title")}
      </h1>
      <p className="mt-6 max-w-2xl text-body-lg text-muted-foreground md:text-xl">
        {t("landing:hero.subtitle")}
      </p>
    </section>
  );
}
