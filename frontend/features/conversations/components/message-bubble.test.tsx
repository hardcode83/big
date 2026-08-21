import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { MessageSenderType, ThreadMessage } from "../data/dto";
import { MessageBubble } from "./message-bubble";

function message(overrides: Partial<ThreadMessage> = {}): ThreadMessage {
  return {
    id: "message-1",
    conversationId: "conversation-1",
    senderType: "GUEST",
    senderUserId: null,
    content: "No funciona el agua caliente",
    language: "es",
    intent: null,
    aiGenerated: false,
    confidenceScore: null,
    deliveryStatus: null,
    escalationReason: null,
    createdAt: "2026-08-19T10:00:00Z",
    ...overrides,
  };
}

function renderBubble(overrides: Partial<ThreadMessage> = {}) {
  return render(
    <I18nProvider locale="es">
      <ul>
        <MessageBubble message={message(overrides)} />
      </ul>
    </I18nProvider>,
  );
}

describe("MessageBubble — the five senders (task 6.1, R3.3)", () => {
  it.each([
    ["GUEST", "Huésped", "guest"],
    ["OWNER", "Propietaria", "us"],
    ["MANAGER", "Manager", "us"],
    ["AI", "IA", "us"],
    ["SYSTEM", "Sistema", "system"],
  ] as const)("labels %s and puts it on the %s side", (senderType, label, side) => {
    renderBubble({ senderType: senderType as MessageSenderType });

    expect(screen.getByText(label)).toBeInTheDocument();
    const bubble = screen.getByRole("listitem");
    expect(bubble).toHaveAttribute("data-sender", senderType);
    expect(bubble).toHaveAttribute("data-side", side);
  });

  it("aligns the guest opposite to us", () => {
    const { unmount } = renderBubble({ senderType: "GUEST" });
    expect(screen.getByRole("listitem").className).toContain("mr-auto");
    unmount();

    renderBubble({ senderType: "MANAGER" });
    expect(screen.getByRole("listitem").className).toContain("ml-auto");
  });
});

describe("MessageBubble — the AI's marks (task 6.1, R3.4, D8, D14)", () => {
  it("marks an AI message with its intent and its confidence as a percentage", () => {
    const { container } = renderBubble({
      senderType: "AI",
      aiGenerated: true,
      intent: "CHECKIN_INFO",
      confidenceScore: "0.8750",
    });

    expect(screen.getByText("Generado por IA")).toBeInTheDocument();
    expect(container.textContent).toContain("CHECKIN_INFO");
    // Asserted on textContent, not through a text matcher: the Spanish percent
    // format separates the figure with a non-breaking space, which the query
    // normalizer does not collapse.
    const expected = new Intl.NumberFormat("es", {
      style: "percent",
      maximumFractionDigits: 0,
    }).format(0.875);
    expect(container.textContent).toContain(expected);
    expect(container.textContent).toContain("Confianza");
  });

  it("omits the figure entirely when confidence_score is null, with no null and no NaN", () => {
    const { container } = renderBubble({
      senderType: "AI",
      aiGenerated: true,
      intent: "OTHER",
      confidenceScore: null,
    });

    expect(screen.getByText("Generado por IA")).toBeInTheDocument();
    expect(screen.queryByText(/Confianza/)).toBeNull();
    expect(container.textContent).not.toContain("null");
    expect(container.textContent).not.toContain("NaN");
  });

  it("shows no AI marks on a human message even if it carries an intent", () => {
    const { container } = renderBubble({
      senderType: "MANAGER",
      aiGenerated: false,
      intent: "CHECKIN_INFO",
      confidenceScore: "0.9",
    });

    expect(screen.queryByText("Generado por IA")).toBeNull();
    expect(container.textContent).not.toContain("CHECKIN_INFO");
    expect(container.textContent).not.toContain("Confianza");
  });

  it("marks a reply the guest never received (D14)", () => {
    const { container } = renderBubble({
      senderType: "AI",
      aiGenerated: true,
      deliveryStatus: "FAILED",
      escalationReason: "DELIVERY_FAILED",
    });

    expect(screen.getByText("No entregado al huésped")).toBeInTheDocument();
    // D14 asks the DTO to carry `escalation_reason` and asks for the delivery
    // mark; it does not ask for the reason to be shown, so it is not.
    expect(container.textContent).not.toContain("DELIVERY_FAILED");
  });

  it("shows no delivery mark when the message was delivered", () => {
    renderBubble({ senderType: "AI", aiGenerated: true, deliveryStatus: "SENT" });
    expect(screen.queryByText("No entregado al huésped")).toBeNull();
  });
});

describe("MessageBubble — content is text and nothing else (task 6.2, D15)", () => {
  const HOSTILE =
    '<img src=x onerror="alert(1)"> visita https://evil.example y <b>pincha</b>';

  it("shows a hostile content literally, generating no active nodes", () => {
    const { container } = renderBubble({ content: HOSTILE });

    const paragraph = container.querySelector("p")!;
    expect(paragraph.textContent).toBe(HOSTILE);
    expect(paragraph.querySelector("img")).toBeNull();
    expect(paragraph.querySelector("b")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    // The payload survives as text — `onerror` appears escaped inside the
    // paragraph and nowhere as an attribute, which is the whole distinction.
    expect(container.innerHTML).toContain("&lt;img");
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(
      Array.from(paragraph.querySelectorAll("*")),
      "the content must produce no element nodes at all",
    ).toEqual([]);
  });

  it("does not autolink a bare URL", () => {
    const { container } = renderBubble({
      content: "Mira https://example.com/aviso",
    });
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("p")!.textContent).toContain(
      "https://example.com/aviso",
    );
  });

  it("preserves line breaks without turning them into markup", () => {
    const { container } = renderBubble({ content: "Primera\n\nSegunda" });
    const paragraph = container.querySelector("p")!;

    expect(paragraph.className).toContain("whitespace-pre-wrap");
    expect(paragraph.textContent).toBe("Primera\n\nSegunda");
    expect(paragraph.querySelector("br")).toBeNull();
  });

  it("does not truncate or summarize a long message", () => {
    const long = "a".repeat(4000);
    const { container } = renderBubble({ content: long });
    expect(container.querySelector("p")!.textContent).toHaveLength(4000);
    expect(container.textContent).not.toContain("…");
  });
});
