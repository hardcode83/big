import { describe, expect, it, vi } from "vitest";

import { getA11yViolations, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { BlockedTransitionSummary } from "@/features/dashboard/stalls";

import type { PropertyDashboardCard } from "../data";
import { PropertyCard } from "./property-card";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const card: PropertyDashboardCard = {
  propertyId: "redes11",
  propertyCode: "REDES11",
  operationalState: "AWAITING_CLEANING",
  currentOrNextReservation: {
    id: "r1",
    reference: "Booking.com #1234",
    guestName: "Laura Gómez",
    checkIn: "2026-07-31T13:00:00Z",
    checkOut: "2026-08-04T09:00:00Z",
  },
  cleaningStatus: "Pendiente de asignar",
  openIncidentsCount: 2,
  nextAction: { label: "Asignar limpiadora", responsible: "Manager" },
  lastEventLabel: "Tarea creada",
  lastEventAt: "2026-07-30T09:12:00Z",
};

function renderCard(node: React.ReactNode, locale: "es" | "en" = "es") {
  return render(<I18nProvider locale={locale}>{node}</I18nProvider>);
}

describe("PropertyCard (R1, R5)", () => {
  it("renders the §9.1 fields from the DTO", () => {
    renderCard(<PropertyCard card={card} />);

    expect(screen.getByText("REDES11")).toBeInTheDocument();
    // Localized operational-state label (es), not the raw enum.
    expect(screen.getByText("Pendiente de limpieza")).toBeInTheDocument();
    expect(screen.getByText("Booking.com #1234")).toBeInTheDocument();
    expect(screen.getByText("Laura Gómez")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/Asignar limpiadora/)).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/properties/redes11",
    );
  });

  it("renders localized fallbacks when reservation data is absent", () => {
    renderCard(
      <PropertyCard
        card={{
          ...card,
          currentOrNextReservation: null,
          cleaningStatus: null,
        }}
      />,
    );
    expect(screen.getByText("Sin reserva")).toBeInTheDocument();
    expect(screen.getByText("Sin huésped")).toBeInTheDocument();
  });

  it("uses English copy under the en locale", () => {
    renderCard(<PropertyCard card={card} />, "en");
    expect(screen.getByText("Awaiting cleaning")).toBeInTheDocument();
    expect(screen.getByText("View detail")).toBeInTheDocument();
  });

  it("keeps the operational regions in priority order", () => {
    renderCard(<PropertyCard card={card} />);

    const sections = Array.from(screen.getByRole("article").querySelectorAll("section"));
    expect(
      sections.map(
        (section) => section.getAttribute("aria-label") ?? section.querySelector("h4")?.textContent,
      ),
    ).toEqual(["Incidencias abiertas", "Próxima acción", "Reserva", "Limpieza", "Último evento"]);
  });

  it("renders the blocked-transitions section when stalls are present, keeping region order (R1.3, blocked-transitions-web)", () => {
    const stalls: BlockedTransitionSummary[] = [
      {
        property_id: "redes11",
        property_code: "REDES11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-23T13:00:00Z",
      },
    ];

    renderCard(<PropertyCard card={card} stalls={stalls} />);

    // Section is rendered.
    expect(
      screen.getByRole("heading", { level: 4, name: "Bloqueos" }),
    ).toBeInTheDocument();

    // Canonical literals are rendered in <code> tags.
    expect(screen.getByText("CHECKIN_TIME_REACHED")).toBeInTheDocument();
    expect(screen.getByText("AWAITING_CLEANING")).toBeInTheDocument();

    // Region order preserved (R1.3): incidents → stalls → next action → reservation → cleaning → last event.
    const sections = Array.from(
      screen.getByRole("article").querySelectorAll("section"),
    );
    expect(
      sections.map(
        (section) =>
          section.getAttribute("aria-label") ??
          section.querySelector("h4")?.textContent,
      ),
    ).toEqual([
      "Incidencias abiertas",
      "Bloqueos",
      "Próxima acción",
      "Reserva",
      "Limpieza",
      "Último evento",
    ]);
  });

  it("renders the blocked-transitions section under the en locale (R4.1)", () => {
    const stalls: BlockedTransitionSummary[] = [
      {
        property_id: "redes11",
        property_code: "REDES11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-23T13:00:00Z",
      },
    ];

    renderCard(<PropertyCard card={card} stalls={stalls} />, "en");

    expect(
      screen.getByRole("heading", { level: 4, name: "Blockers" }),
    ).toBeInTheDocument();
  });

  it("renders no stalls section when stalls is empty or undefined (R1.3)", () => {
    const { rerender } = renderCard(<PropertyCard card={card} />);
    expect(screen.queryByRole("heading", { level: 4, name: "Bloqueos" })).toBeNull();

    rerender(<I18nProvider locale="es"><PropertyCard card={card} stalls={[]} /></I18nProvider>);
    expect(screen.queryByRole("heading", { level: 4, name: "Bloqueos" })).toBeNull();
  });

  it("exposes a localized accessible detail link", () => {
    renderCard(<PropertyCard card={card} />);
    expect(screen.getByRole("link", { name: "Ver detalle" })).toHaveAttribute(
      "href",
      "/properties/redes11",
    );
  });

  it("has no axe violations", async () => {
    const { container } = renderCard(<PropertyCard card={card} />);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
