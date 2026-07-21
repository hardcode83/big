import { ModulePlaceholder } from "@/components/states";
import { createServerI18n, getServerLocale } from "@/lib/i18n/server";
import { getRouteById } from "../navigation/route-registry";
import { navigationIcons } from "./icon-map";

/**
 * Server Component that renders a route's planned-module placeholder (design
 * D8/D9). It resolves the localized copy on the server from the route registry
 * keys and passes them to the presentational ModulePlaceholder. For dynamic
 * routes the param is never read or rendered — only the stable route id is used.
 */
export async function RoutePlaceholder({ routeId }: { routeId: string }) {
  const route = getRouteById(routeId);
  if (!route) {
    return null;
  }
  const locale = await getServerLocale();
  const i18n = await createServerI18n(locale);
  const t = i18n.getFixedT(locale, null);
  const Icon = navigationIcons[route.icon];

  return (
    <ModulePlaceholder
      icon={<Icon className="size-10" aria-hidden="true" />}
      badgeLabel={t("states:placeholder.badge")}
      title={t(route.titleKey)}
      description={t(route.descriptionKey)}
      explanation={t("states:placeholder.explanation")}
    />
  );
}
