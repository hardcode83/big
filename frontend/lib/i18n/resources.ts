import esCommon from "@/locales/es/common.json";
import esNavigation from "@/locales/es/navigation.json";
import esStates from "@/locales/es/states.json";
import enCommon from "@/locales/en/common.json";
import enNavigation from "@/locales/en/navigation.json";
import enStates from "@/locales/en/states.json";

/** i18next namespaces (design D13). */
export const NAMESPACES = ["common", "navigation", "states"] as const;
export const DEFAULT_NS = "common";

/** Static translation resources shared by the server and client instances. */
export const resources = {
  es: { common: esCommon, navigation: esNavigation, states: esStates },
  en: { common: enCommon, navigation: enNavigation, states: enStates },
} as const;
