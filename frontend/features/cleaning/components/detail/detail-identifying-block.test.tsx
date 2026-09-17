import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { PropertySummary } from "../../data";
import { buildDirectory } from "../../lib/directory";
import { DetailIdentifyingBlock } from "./detail-identifying-block";

const PROPERTY_UUID = "8f14e45f-ceea-467a-9b7c-9d7c1a2b3c4d";

const PROPS: PropertySummary[] = [
  {
    id: PROPERTY_UUID,
    name: "Redes 11",
    internalCode: "REDES11",
    currentOperationalState: "AWAITING_CLEANING",
  },
];

function settled<T extends { id: string }>(entries: readonly T[]) {
  return { index: buildDirectory(entries), isPending: false };
}

function renderBlock(
  overrides: Partial<React.ComponentProps<typeof DetailIdentifyingBlock>> = {},
) {
  const props = {
    propertyId: PROPERTY_UUID,
    reservationId: "reservation-1" as string | null,
    properties: settled(PROPS),
    ...overrides,
  };
  return render(
    <I18nProvider locale="es">
      <DetailIdentifyingBlock {...props} />
    </I18nProvider>,
  );
}

const PROPERTY_CODE_LABEL = "Código de la vivienda";
const PROPERTY_NAME_LABEL = "Nombre de la vivienda";
const RESERVATION_CODE_LABEL = "Código de la reserva";
const PROPERTY_NOT_FOUND_KEY = "Vivienda no disponible";
const RESERVATION_NOT_FOUND_LABEL = "Reserva no disponible";

describe("DetailIdentifyingBlock (proposal R3.1/R3.2/R3.4)", () => {
  it("names the property by code and name, never by id (R3.1)", () => {
    const { container } = renderBlock();
    expect(screen.getByText("REDES11")).toBeInTheDocument();
    expect(screen.getByText("Redes 11")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain(PROPERTY_UUID);
  });

  it("paints the reservation id as the code (R3.2)", () => {
    renderBlock({ reservationId: "RES-42" });
    expect(screen.getByText("RES-42")).toBeInTheDocument();
    expect(screen.getByText(RESERVATION_CODE_LABEL)).toBeInTheDocument();
  });

  it("degrades to 'reservation not available' when reservationId is null (R3.2)", () => {
    renderBlock({ reservationId: null });
    expect(screen.getByText(RESERVATION_NOT_FOUND_LABEL)).toBeInTheDocument();
    expect(screen.queryByText("RES-42")).not.toBeInTheDocument();
  });

  it("degrades to 'property not available' when the directory has no match (R3.4)", () => {
    const { container } = renderBlock({
      propertyId: "missing-uuid",
      properties: settled([]),
    });
    // The fallback appears in BOTH the code and the name fields, so two
    // occurrences are expected.
    expect(screen.getAllByText(PROPERTY_NOT_FOUND_KEY).length).toBe(2);
    expect(container.innerHTML).not.toContain("missing-uuid");
  });

  it("keeps the property identity in the section title (R3.1)", () => {
    renderBlock();
    expect(screen.getByText(PROPERTY_CODE_LABEL)).toBeInTheDocument();
    expect(screen.getByText(PROPERTY_NAME_LABEL)).toBeInTheDocument();
  });
});