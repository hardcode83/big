import { describe, expect, it } from "vitest";

import { getA11yViolations, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { PropertyDetail } from "../../data";
import { PropertyDetailSections } from "./property-detail-sections";

const detail: PropertyDetail = {
  propertyId: "pajaritos8",
  propertyCode: "PAJARITOS8",
  operationalState: "OCCUPIED_ESTIMATED",
  currentOrNextReservation: {
    id: "r1",
    reference: "Airbnb #A-9981",
    guestName: "Marco Ferri",
    checkIn: "2026-07-28T15:00:00Z",
    checkOut: "2026-07-31T11:00:00Z",
  },
  guest: { name: "Marco Ferri" },
  access: { label: "Código entregado" },
  cleaningStatus: null,
  lastCleaningPhotos: [
    {
      id: "p1",
      url: "https://cdn.example.invalid/mock/photo.jpg",
      takenAt: "2026-07-25T12:05:00Z",
    },
  ],
  openIncidents: [
    { id: "i1", title: "Fuga en cocina", severity: "MEDIUM", openedAt: "2026-07-30T07:41:00Z" },
  ],
  financial: { currency: "EUR", reservationTotal: 447, pendingExpenses: 120 },
  notes: null,
  pendingApprovals: [
    { id: "a1", label: "Reparación fontanería", amount: 120, currency: "EUR" },
  ],
};

function renderSections(node: React.ReactNode, locale: "es" | "en" = "es") {
  return render(<I18nProvider locale={locale}>{node}</I18nProvider>);
}

describe("PropertyDetailSections (R2)", () => {
  it("renders the §9.2 sections from the DTO", () => {
    renderSections(<PropertyDetailSections detail={detail} />);

    expect(screen.getByText("Airbnb #A-9981")).toBeInTheDocument();
    expect(screen.getByText("Marco Ferri")).toBeInTheDocument();
    expect(screen.getByText("Código entregado")).toBeInTheDocument();
    expect(screen.getByText("Fuga en cocina")).toBeInTheDocument();
    expect(screen.getByText("Reparación fontanería")).toBeInTheDocument();
  });

  it("uses the backend-provided photo URL verbatim (never constructed)", () => {
    renderSections(<PropertyDetailSections detail={detail} />);
    const img = screen.getByAltText("Foto de la última limpieza");
    expect(img).toHaveAttribute("src", "https://cdn.example.invalid/mock/photo.jpg");
  });

  it("renders localized fallbacks for empty sections", () => {
    renderSections(
      <PropertyDetailSections
        detail={{
          ...detail,
          cleaningStatus: null,
          notes: null,
          lastCleaningPhotos: [],
          openIncidents: [],
          pendingApprovals: [],
        }}
      />,
    );
    expect(screen.getByText("Sin notas")).toBeInTheDocument();
    expect(screen.getByText("Sin incidencias abiertas")).toBeInTheDocument();
    expect(screen.getByText("Sin aprobaciones pendientes")).toBeInTheDocument();
    expect(screen.getByText("Sin fotos de la última limpieza")).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = renderSections(<PropertyDetailSections detail={detail} />);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
