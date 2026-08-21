import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { ConversationChannel, ConversationDetail } from "../data/dto";
import { ThreadHeader } from "./thread-header";

const MUTE_WARNING =
  "Este canal es mudo por diseño hasta que llegue el adaptador de mensajería del PMS: lo que escribas se guarda en el hilo, pero no se envía al huésped.";
const NOT_REALTIME =
  "El hilo no se actualiza en tiempo real: se refresca al operar sobre él o al recargar la página.";

function conversation(
  overrides: Partial<ConversationDetail> = {},
): ConversationDetail {
  return {
    id: "conversation-1",
    propertyId: "property-1",
    guestId: null,
    reservationId: null,
    channel: "WHATSAPP",
    status: "OPEN",
    escalationStatus: "NONE",
    language: "es",
    aiEnabled: true,
    lastMessageAt: "2026-08-19T10:00:00Z",
    createdAt: "2026-08-10T09:00:00Z",
    updatedAt: "2026-08-19T10:00:00Z",
    ...overrides,
  };
}

function renderHeader(overrides: Partial<ConversationDetail> = {}) {
  return render(
    <I18nProvider locale="es">
      <ThreadHeader conversation={conversation(overrides)} />
    </I18nProvider>,
  );
}

describe("ThreadHeader — language, channel and state (task 6.4, R3.7)", () => {
  it("shows the detected language and the channel", () => {
    renderHeader();
    expect(screen.getByText(/Idioma detectado: es/)).toBeInTheDocument();
    expect(screen.getByText("WhatsApp")).toBeInTheDocument();
    expect(screen.getByText("Abierta")).toBeInTheDocument();
    expect(screen.getByText("Sin escalar")).toBeInTheDocument();
  });

  it("always says the thread is not real time", () => {
    renderHeader();
    expect(screen.getByText(NOT_REALTIME)).toBeInTheDocument();
  });
});

describe("ThreadHeader — the mute-channel warning (task 6.4, D13)", () => {
  it.each(["AIRBNB_MSG", "BOOKING_MSG"] as const)(
    "warns on %s that the reply is stored and not sent",
    (channel) => {
      renderHeader({ channel: channel as ConversationChannel });

      const warning = screen.getByText(MUTE_WARNING);
      expect(warning).toBeInTheDocument();
      // D13: the wording must not promise a failure — replying really returns 201.
      expect(warning.textContent).toContain("se guarda");
      expect(warning.textContent).toContain("no se envía");
      expect(warning.textContent).not.toMatch(/fallar|error/i);
    },
  );

  it("makes the same promise in English, and does not imply a failure either", () => {
    render(
      <I18nProvider locale="en">
        <ThreadHeader conversation={conversation({ channel: "AIRBNB_MSG" })} />
      </I18nProvider>,
    );

    const warning = screen.getByText(/mute by design/);
    expect(warning.textContent).toContain("is stored in the thread");
    expect(warning.textContent).toContain("not sent to the guest");
    expect(warning.textContent).not.toMatch(/fail|error/i);
  });

  it.each(["WHATSAPP", "EMAIL", "PHONE_TRANSCRIPT", "MANUAL"] as const)(
    "does not warn on %s",
    (channel) => {
      renderHeader({ channel: channel as ConversationChannel });
      expect(screen.queryByText(MUTE_WARNING)).toBeNull();
    },
  );
});
