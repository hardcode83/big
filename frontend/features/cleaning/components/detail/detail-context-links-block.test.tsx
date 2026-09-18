import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import { DetailContextLinksBlock } from "./detail-context-links-block";

const PROPERTY_UUID = "8f14e45f-ceea-467a-9b7c-9d7c1a2b3c4d";
const RESERVATION_UUID = "0d4ce0e0-1234-4abc-9b7c-9d7c1a2b3c4d";

function renderBlock(
  overrides: Partial<React.ComponentProps<typeof DetailContextLinksBlock>> = {},
) {
  const props = {
    propertyId: PROPERTY_UUID,
    reservationId: RESERVATION_UUID as string | null,
    canReadProperties: true,
    canReadReservations: true,
    ...overrides,
  };
  return render(
    <I18nProvider locale="es">
      <DetailContextLinksBlock {...props} />
    </I18nProvider>,
  );
}

describe("DetailContextLinksBlock (proposal R4.1/R4.2/R4.3)", () => {
  it("renders the 'back to list' link unconditionally (R4.2)", () => {
    const { container } = renderBlock({
      canReadProperties: false,
      canReadReservations: false,
    });
    const back = screen.getByRole("link", { name: /Volver al listado/ });
    expect(back).toHaveAttribute("href", "/cleaning");
    expect(container.innerHTML).not.toContain(`/properties/`);
  });

  it("renders 'view property' when the viewer has READ_PROPERTIES (R4.1)", () => {
    renderBlock();
    const link = screen.getByRole("link", {
      name: /Ver vivienda/,
    });
    expect(link).toHaveAttribute("href", `/properties/${PROPERTY_UUID}`);
  });

  it("hides 'view property' when the viewer lacks READ_PROPERTIES (R4.1)", () => {
    const { container } = renderBlock({ canReadProperties: false });
    expect(
      screen.queryByRole("link", { name: /Ver vivienda/ }),
    ).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(`/properties/`);
  });

  it("renders 'view reservation' when the viewer has READ_RESERVATIONS and reservationId is set (R4.3)", () => {
    renderBlock();
    const link = screen.getByRole("link", {
      name: /Ver reserva/,
    });
    expect(link).toHaveAttribute("href", `/reservations/${RESERVATION_UUID}`);
  });

  it("hides 'view reservation' when reservationId is null (R4.3)", () => {
    const { container } = renderBlock({ reservationId: null });
    expect(
      screen.queryByRole("link", { name: /Ver reserva/ }),
    ).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(`/reservations/`);
  });

  it("hides 'view reservation' when the viewer lacks READ_RESERVATIONS (R4.3)", () => {
    const { container } = renderBlock({ canReadReservations: false });
    expect(
      screen.queryByRole("link", { name: /Ver reserva/ }),
    ).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(`/reservations/`);
  });
});