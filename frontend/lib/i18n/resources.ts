import esCommon from "@/locales/es/common.json";
import esNavigation from "@/locales/es/navigation.json";
import esStates from "@/locales/es/states.json";
import esDashboard from "@/locales/es/dashboard.json";
import esAuth from "@/locales/es/auth.json";
import enCommon from "@/locales/en/common.json";
import enNavigation from "@/locales/en/navigation.json";
import enStates from "@/locales/en/states.json";
import enDashboard from "@/locales/en/dashboard.json";
import enAuth from "@/locales/en/auth.json";
import esGuest from "@/locales/es/guest.json";
import enGuest from "@/locales/en/guest.json";
import esCleaning from "@/locales/es/cleaning.json";
import enCleaning from "@/locales/en/cleaning.json";

/** i18next namespaces (design D13). */
export const NAMESPACES = ["common", "navigation", "states", "dashboard", "auth", "guest", "cleaning"] as const;
export const DEFAULT_NS = "common";

/** Static translation resources shared by the server and client instances. */
export const resources = {
  es: {
    common: esCommon,
    navigation: esNavigation,
    states: esStates,
    dashboard: esDashboard,
    auth: esAuth,
    guest: esGuest,
    cleaning: esCleaning,
  },
  en: {
    common: enCommon,
    navigation: enNavigation,
    states: enStates,
    dashboard: enDashboard,
    auth: enAuth,
    guest: enGuest,
    cleaning: enCleaning,
  },
} as const;
