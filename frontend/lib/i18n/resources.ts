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
import esReservations from "@/locales/es/reservations.json";
import enReservations from "@/locales/en/reservations.json";
import esIncidents from "@/locales/es/incidents.json";
import enIncidents from "@/locales/en/incidents.json";
import esCleaning from "@/locales/es/cleaning.json";
import enCleaning from "@/locales/en/cleaning.json";
import esProperties from "@/locales/es/properties.json";
import enProperties from "@/locales/en/properties.json";

/** i18next namespaces (design D13). */
export const NAMESPACES = [
  "common",
  "navigation",
  "states",
  "dashboard",
  "auth",
  "guest",
  "reservations",
  "incidents",
  "cleaning",
  "properties",
] as const;
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
    reservations: esReservations,
    incidents: esIncidents,
    cleaning: esCleaning,
    properties: esProperties,
  },
  en: {
    common: enCommon,
    navigation: enNavigation,
    states: enStates,
    dashboard: enDashboard,
    auth: enAuth,
    guest: enGuest,
    reservations: enReservations,
    incidents: enIncidents,
    cleaning: enCleaning,
    properties: enProperties,
  },
} as const;
