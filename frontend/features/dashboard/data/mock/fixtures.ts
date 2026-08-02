/**
 * ASSUMPTION / DEBT (dashboard-web): fixed, in-memory dashboard data for the two
 * real dev properties (REDES11, PAJARITOS8). This is the *only* place business
 * data is invented in this change; it exists solely because the aggregate
 * dashboard backend (GET /api/v1/properties/{id}/dashboard) does not exist yet.
 * When dashboard-web ships, `HttpDashboardSource` replaces `MockDashboardSource`
 * and this module is deleted.
 *
 * Dynamic human-readable text (`LocalizedText`) is written in Spanish here: the
 * real backend localizes per authenticated user, but this mock is not
 * locale-aware. Static UI chrome is localized separately via react-i18next.
 */
import type {
  PropertyDashboardCard,
  PropertyDetail,
  TimelineEntry,
} from "../dto";

export const MOCK_PROPERTY_IDS = ["redes11", "pajaritos8"] as const;

export const MOCK_DASHBOARD_CARDS: readonly PropertyDashboardCard[] = [
  {
    propertyId: "redes11",
    propertyCode: "REDES11",
    operationalState: "AWAITING_CLEANING",
    currentOrNextReservation: {
      id: "res-redes11-next",
      reference: "Booking.com #1234",
      guestName: "Laura Gómez",
      checkIn: "2026-07-31T13:00:00Z",
      checkOut: "2026-08-04T09:00:00Z",
    },
    cleaningStatus: "Pendiente de asignar",
    openIncidentsCount: 0,
    nextAction: {
      label: "Asignar limpiadora antes del próximo check-in",
      responsible: "Manager",
    },
    lastEventLabel: "Tarea de limpieza creada",
    lastEventAt: "2026-07-30T09:12:00Z",
  },
  {
    propertyId: "pajaritos8",
    propertyCode: "PAJARITOS8",
    operationalState: "OCCUPIED_ESTIMATED",
    currentOrNextReservation: {
      id: "res-pajaritos8-current",
      reference: "Airbnb #A-9981",
      guestName: "Marco Ferri",
      checkIn: "2026-07-28T15:00:00Z",
      checkOut: "2026-07-31T11:00:00Z",
    },
    cleaningStatus: null,
    openIncidentsCount: 1,
    nextAction: {
      label: "Revisar incidencia de fontanería reportada por el huésped",
      responsible: "Manager",
    },
    lastEventLabel: "Incidencia reportada por el huésped",
    lastEventAt: "2026-07-30T07:41:00Z",
  },
];

export const MOCK_PROPERTY_DETAILS: Readonly<Record<string, PropertyDetail>> = {
  redes11: {
    propertyId: "redes11",
    propertyCode: "REDES11",
    operationalState: "AWAITING_CLEANING",
    currentOrNextReservation: {
      id: "res-redes11-next",
      reference: "Booking.com #1234",
      guestName: "Laura Gómez",
      checkIn: "2026-07-31T13:00:00Z",
      checkOut: "2026-08-04T09:00:00Z",
    },
    guest: { name: "Laura Gómez" },
    access: { label: "Código pendiente de generar" },
    cleaningStatus: "Pendiente de asignar",
    lastCleaningPhotos: [
      {
        id: "photo-redes11-1",
        url: "https://cdn.example.invalid/mock/redes11-bathroom.jpg",
        takenAt: "2026-07-25T12:05:00Z",
      },
    ],
    openIncidents: [],
    financial: {
      currency: "EUR",
      reservationTotal: 612,
      pendingExpenses: 0,
    },
    notes: "Dejar el aire acondicionado a 24 ºC para el próximo check-in.",
    pendingApprovals: [],
  },
  pajaritos8: {
    propertyId: "pajaritos8",
    propertyCode: "PAJARITOS8",
    operationalState: "OCCUPIED_ESTIMATED",
    currentOrNextReservation: {
      id: "res-pajaritos8-current",
      reference: "Airbnb #A-9981",
      guestName: "Marco Ferri",
      checkIn: "2026-07-28T15:00:00Z",
      checkOut: "2026-07-31T11:00:00Z",
    },
    guest: { name: "Marco Ferri" },
    access: { label: "Código entregado" },
    cleaningStatus: null,
    lastCleaningPhotos: [],
    openIncidents: [
      {
        id: "inc-pajaritos8-1",
        title: "Fuga bajo el fregadero de la cocina",
        severity: "MEDIUM",
        openedAt: "2026-07-30T07:41:00Z",
      },
    ],
    financial: {
      currency: "EUR",
      reservationTotal: 447,
      pendingExpenses: 120,
    },
    notes: null,
    pendingApprovals: [
      {
        id: "appr-pajaritos8-1",
        label: "Reparación de fontanería (fuga en cocina)",
        amount: 120,
        currency: "EUR",
      },
    ],
  },
};

export const MOCK_PROPERTY_TIMELINES: Readonly<
  Record<string, readonly TimelineEntry[]>
> = {
  redes11: [
    {
      id: "tl-redes11-1",
      occurredAt: "2026-07-30T09:10:00Z",
      actorType: "SCHEDULER",
      eventType: "CHECKOUT_WINDOW_REACHED",
      severity: "INFO",
      title: "Hora de checkout alcanzada para la reserva Booking.com #1180.",
      description: null,
    },
    {
      id: "tl-redes11-2",
      occurredAt: "2026-07-30T09:12:00Z",
      actorType: "SYSTEM",
      eventType: "CLEANING_TASK_CREATED",
      severity: "INFO",
      title: "Tarea de limpieza creada automáticamente.",
      description: null,
    },
    {
      id: "tl-redes11-3",
      occurredAt: "2026-07-30T09:12:30Z",
      actorType: "SYSTEM",
      eventType: "PROPERTY_STATE_CHANGED",
      severity: "INFO",
      title: "Estado de la propiedad: AWAITING_CLEANING.",
      description: null,
    },
  ],
  pajaritos8: [
    {
      id: "tl-pajaritos8-1",
      occurredAt: "2026-07-28T15:02:00Z",
      actorType: "SYSTEM",
      eventType: "ACCESS_CODE_DELIVERED",
      severity: "INFO",
      title: "Código de acceso entregado al huésped.",
      description: null,
    },
    {
      id: "tl-pajaritos8-2",
      occurredAt: "2026-07-30T07:41:00Z",
      actorType: "GUEST",
      eventType: "GUEST_MESSAGE_RECEIVED",
      severity: "WARNING",
      title: "El huésped reporta una fuga bajo el fregadero de la cocina.",
      description: "Mensaje recibido por el canal de mensajería.",
    },
  ],
};
