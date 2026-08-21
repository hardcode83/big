import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpConversationsSource } from "./http-conversations-source";

function sourceWith(response: unknown): {
  source: HttpConversationsSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  return {
    source: new HttpConversationsSource({ request } as unknown as ApiClient),
    request,
  };
}

const conversation = {
  id: "conversation-1",
  property_id: null,
  guest_id: null,
  reservation_id: null,
  channel: "WHATSAPP",
  status: "OPEN",
  escalation_status: "NONE",
  language: "es",
  ai_enabled: true,
  last_message_at: null,
  created_at: "2026-08-19T09:00:00Z",
  updated_at: "2026-08-19T09:30:00+02:00",
};

const message = {
  id: "message-1",
  conversation_id: "conversation-1",
  sender_type: "AI",
  sender_user_id: null,
  content: "Hola",
  language: "es",
  intent: "CHECKIN_INFO",
  ai_generated: true,
  confidence_score: "0.8750",
  metadata: {
    delivery_status: "FAILED",
    escalation_reason: "DELIVERY_FAILED",
    template_id: "tpl-7",
  },
  created_at: "2026-08-19T10:00:00Z",
};

describe("HttpConversationsSource — page mapping (task 1.4, R7.2, R1.3)", () => {
  it("derives totalPages from the messaging envelope and preserves nulls and ISO strings", async () => {
    const { source } = sourceWith({
      items: [conversation],
      page: 2,
      per_page: 20,
      total: 41,
    });

    await expect(
      source.listConversations("tenant-1", {}, 2, 20),
    ).resolves.toEqual({
      items: [
        {
          id: "conversation-1",
          propertyId: null,
          guestId: null,
          reservationId: null,
          channel: "WHATSAPP",
          status: "OPEN",
          escalationStatus: "NONE",
          language: "es",
          aiEnabled: true,
          lastMessageAt: null,
          createdAt: "2026-08-19T09:00:00Z",
          updatedAt: "2026-08-19T09:30:00+02:00",
        },
      ],
      page: 2,
      perPage: 20,
      total: 41,
      totalPages: 3,
    });
  });

  it("keeps an empty inbox at one page instead of zero", async () => {
    const { source } = sourceWith({ items: [], page: 1, per_page: 20, total: 0 });
    await expect(source.listConversations("tenant-1", {}, 1, 20)).resolves.toMatchObject(
      { items: [], totalPages: 1 },
    );
  });

  it("derives totalPages for the thread envelope too", async () => {
    const { source } = sourceWith({
      items: [message],
      page: 1,
      per_page: 50,
      total: 51,
    });
    await expect(
      source.listMessages("tenant-1", "conversation-1", 1, 50),
    ).resolves.toMatchObject({ page: 1, perPage: 50, total: 51, totalPages: 2 });
  });

  it("reads data and total_pages from the properties envelope instead of deriving them", async () => {
    const { source } = sourceWith({
      data: [
        {
          id: "property-1",
          internal_code: "REDES11",
          name: "Redes 11",
          access_notes: "Caja fuerte junto al portal",
          emergency_notes: "Llamar al 112",
          wifi_name: "REDES11-WIFI",
          has_wifi_password: true,
        },
      ],
      page: 1,
      per_page: 100,
      total: 1,
      total_pages: 7,
    });

    const page = await source.listPropertyLabels("tenant-1");

    expect(page).toEqual({
      items: [{ id: "property-1", internalCode: "REDES11", name: "Redes 11" }],
      page: 1,
      perPage: 100,
      total: 1,
      totalPages: 7,
    });
    expect(JSON.stringify(page)).not.toContain("access_notes");
    expect(JSON.stringify(page)).not.toContain("REDES11-WIFI");
  });
});

describe("HttpConversationsSource — message mapping (task 1.5, D8, D14, R3.4)", () => {
  it("copies confidence_score as the decimal string, unrounded", async () => {
    const { source } = sourceWith({
      items: [message],
      page: 1,
      per_page: 50,
      total: 1,
    });
    const page = await source.listMessages("tenant-1", "conversation-1", 1, 50);
    expect(page.items[0].confidenceScore).toBe("0.8750");
    expect(typeof page.items[0].confidenceScore).toBe("string");
  });

  it("preserves a null confidence_score", async () => {
    const { source } = sourceWith({
      items: [{ ...message, confidence_score: null }],
      page: 1,
      per_page: 50,
      total: 1,
    });
    const page = await source.listMessages("tenant-1", "conversation-1", 1, 50);
    expect(page.items[0].confidenceScore).toBeNull();
  });

  it("extracts only delivery_status and escalation_reason from metadata", async () => {
    const { source } = sourceWith({
      items: [message],
      page: 1,
      per_page: 50,
      total: 1,
    });
    const page = await source.listMessages("tenant-1", "conversation-1", 1, 50);

    expect(page.items[0]).toEqual({
      id: "message-1",
      conversationId: "conversation-1",
      senderType: "AI",
      senderUserId: null,
      content: "Hola",
      language: "es",
      intent: "CHECKIN_INFO",
      aiGenerated: true,
      confidenceScore: "0.8750",
      deliveryStatus: "FAILED",
      escalationReason: "DELIVERY_FAILED",
      createdAt: "2026-08-19T10:00:00Z",
    });
    expect(page.items[0]).not.toHaveProperty("metadata");
    expect(JSON.stringify(page.items[0])).not.toContain("tpl-7");
  });

  it("maps a metadata without the two keys to two nulls, not undefined", async () => {
    const { source } = sourceWith({
      items: [{ ...message, metadata: { template_id: "tpl-7" } }],
      page: 1,
      per_page: 50,
      total: 1,
    });
    const page = await source.listMessages("tenant-1", "conversation-1", 1, 50);
    expect(page.items[0].deliveryStatus).toBeNull();
    expect(page.items[0].escalationReason).toBeNull();
    expect(page.items[0]).toHaveProperty("deliveryStatus");
    expect(page.items[0]).toHaveProperty("escalationReason");
  });

  it("maps a null metadata to two null fields", async () => {
    const { source } = sourceWith({
      items: [{ ...message, metadata: null }],
      page: 1,
      per_page: 50,
      total: 1,
    });
    const page = await source.listMessages("tenant-1", "conversation-1", 1, 50);
    expect(page.items[0].deliveryStatus).toBeNull();
    expect(page.items[0].escalationReason).toBeNull();
  });
});

describe("HttpConversationsSource — query serialization (task 1.6, R2.1, R1.6, R1.7)", () => {
  it("omits the filters that are not selected and always sends the page", async () => {
    const { source, request } = sourceWith({
      items: [],
      page: 1,
      per_page: 20,
      total: 0,
    });
    await source.listConversations("tenant-1", {}, 1, 20);

    expect(request).toHaveBeenCalledWith("/api/v1/conversations", {
      method: "GET",
      query: { page: 1, per_page: 20 },
    });
  });

  it("sends every selected filter under its contract name", async () => {
    const { source, request } = sourceWith({
      items: [],
      page: 3,
      per_page: 20,
      total: 0,
    });
    await source.listConversations(
      "tenant-1",
      {
        status: "ESCALATED",
        escalationStatus: "PENDING_HUMAN",
        propertyId: "property-1",
      },
      3,
      20,
    );

    expect(request).toHaveBeenCalledWith("/api/v1/conversations", {
      method: "GET",
      query: {
        page: 3,
        per_page: 20,
        status: "ESCALATED",
        escalation_status: "PENDING_HUMAN",
        property_id: "property-1",
      },
    });
  });

  it("pages the thread with page and per_page", async () => {
    const { source, request } = sourceWith({
      items: [],
      page: 2,
      per_page: 50,
      total: 0,
    });
    await source.listMessages("tenant-1", "conversation-1", 2, 50);

    expect(request).toHaveBeenCalledWith(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        method: "GET",
        pathParams: { conversation_id: "conversation-1" },
        query: { page: 2, per_page: 50 },
      },
    );
  });

  it("asks for the property labels once, with per_page 100", async () => {
    const { source, request } = sourceWith({
      data: [],
      page: 1,
      per_page: 100,
      total: 0,
      total_pages: 1,
    });
    await source.listPropertyLabels("tenant-1");

    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      method: "GET",
      query: { page: 1, per_page: 100 },
    });
  });
});

describe("HttpConversationsSource — write bodies (task 1.7, R4.1, R4.2, R5.1)", () => {
  it("replies without sender_type so the backend derives it from the role", async () => {
    const { source, request } = sourceWith(message);
    await source.createMessage("tenant-1", "conversation-1", {
      content: "Vamos a mirarlo",
    });

    expect(request).toHaveBeenCalledWith(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        method: "POST",
        pathParams: { conversation_id: "conversation-1" },
        body: { content: "Vamos a mirarlo" },
      },
    );
    const body = request.mock.calls[0][1].body;
    expect(body).not.toHaveProperty("sender_type");
  });

  it("transcribes a guest message with sender_type GUEST", async () => {
    const { source, request } = sourceWith(message);
    await source.createMessage("tenant-1", "conversation-1", {
      content: "No funciona el agua caliente",
      senderType: "GUEST",
    });

    expect(request).toHaveBeenCalledWith(
      "/api/v1/conversations/{conversation_id}/messages",
      {
        method: "POST",
        pathParams: { conversation_id: "conversation-1" },
        body: {
          content: "No funciona el agua caliente",
          sender_type: "GUEST",
        },
      },
    );
  });

  it("escalates and resolves with no body at all", async () => {
    const { source, request } = sourceWith(conversation);

    await expect(source.escalate("tenant-1", "conversation-1")).resolves.toMatchObject(
      { id: "conversation-1", status: "OPEN" },
    );
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/conversations/{conversation_id}/escalate",
      { method: "POST", pathParams: { conversation_id: "conversation-1" } },
    );

    await source.resolve("tenant-1", "conversation-1");
    expect(request).toHaveBeenLastCalledWith(
      "/api/v1/conversations/{conversation_id}/resolve",
      { method: "POST", pathParams: { conversation_id: "conversation-1" } },
    );
    for (const call of request.mock.calls) {
      expect(call[1]).not.toHaveProperty("body");
    }
  });

  it("reads one conversation by id", async () => {
    const { source, request } = sourceWith(conversation);
    await source.getConversation("tenant-1", "conversation-1");
    expect(request).toHaveBeenCalledWith(
      "/api/v1/conversations/{conversation_id}",
      { method: "GET", pathParams: { conversation_id: "conversation-1" } },
    );
  });
});
