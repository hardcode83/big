import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { ConversationSummary } from "../data/dto";
import { InboxRow } from "./inbox-row";

const NOW = new Date("2026-08-19T12:00:00Z");

const conversation: ConversationSummary = {
  id: "conversation-1",
  propertyId: "property-1",
  guestId: null,
  reservationId: null,
  channel: "WHATSAPP",
  status: "ESCALATED",
  escalationStatus: "PENDING_HUMAN",
  language: "es",
  aiEnabled: true,
  lastMessageAt: "2026-08-16T12:00:00Z",
  createdAt: "2026-08-10T09:00:00Z",
  updatedAt: "2026-08-16T12:00:00Z",
};

const property = {
  id: "property-1",
  internalCode: "REDES11",
  name: "Redes 11",
};

function renderRow(
  overrides: Partial<Parameters<typeof InboxRow>[0]> = {},
) {
  const onSelect = vi.fn();
  render(
    <I18nProvider locale="es">
      <ul>
        <InboxRow
          conversation={conversation}
          property={property}
          isSelected={false}
          onSelect={onSelect}
          {...overrides}
        />
      </ul>
    </I18nProvider>,
  );
  return { onSelect };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("InboxRow — the full row (task 5.1, R1.2)", () => {
  it("shows the property code, channel, both state axes, the language and the age", () => {
    renderRow();

    expect(screen.getByText("REDES11")).toBeInTheDocument();
    expect(screen.getByText("WhatsApp")).toBeInTheDocument();
    expect(screen.getByText("Escalada")).toBeInTheDocument();
    expect(screen.getByText("Esperando a una persona")).toBeInTheDocument();
    expect(screen.getByText("es")).toBeInTheDocument();

    const age = screen.getByText(
      new Intl.RelativeTimeFormat("es", { numeric: "auto" }).format(-3, "day"),
    );
    expect(age.tagName).toBe("TIME");
    expect(age).toHaveAttribute("dateTime", "2026-08-16T12:00:00Z");
  });

  it("keeps the absolute instant in the title, so the relative age is never the only datum (D9)", () => {
    renderRow();
    const absolute = new Intl.DateTimeFormat("es", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date("2026-08-16T12:00:00Z"));
    expect(screen.getByTitle(absolute)).toBeInTheDocument();
  });

  it("selects the conversation when the row is activated", () => {
    const { onSelect } = renderRow();
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith("conversation-1");
  });

  it("marks the selected row for assistive technology", () => {
    renderRow({ isSelected: true });
    expect(screen.getByRole("button")).toHaveAttribute("aria-current", "true");
  });

  it("names the action in the active locale (R7.6)", () => {
    renderRow();
    expect(
      screen.getByRole("button", { name: /Abrir la conversación/ }),
    ).toBeInTheDocument();
  });
});

describe("InboxRow — the rows that could break (task 5.1, R1.3, R1.7)", () => {
  it("says «sin mensajes» instead of inventing a date when last_message_at is null", () => {
    renderRow({ conversation: { ...conversation, lastMessageAt: null } });

    expect(screen.getByText("Sin mensajes")).toBeInTheDocument();
    expect(document.querySelector("time")).toBeNull();
  });

  it("falls back to a localized placeholder when the property is not in the catalogue", () => {
    renderRow({ property: undefined });

    expect(screen.getByText("Propiedad no disponible")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeInTheDocument();
    expect(screen.getByText("WhatsApp")).toBeInTheDocument();
  });

  it("says so when the conversation has no property at all", () => {
    renderRow({
      conversation: { ...conversation, propertyId: null },
      property: undefined,
    });
    expect(screen.getByText("Sin propiedad")).toBeInTheDocument();
  });
});
