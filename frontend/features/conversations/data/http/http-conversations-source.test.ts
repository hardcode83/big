import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpConversationsSource } from "./http-conversations-source";

function buildClient(impl: ReturnType<typeof vi.fn>): ApiClient {
  return { request: impl } as unknown as ApiClient;
}

describe("HttpConversationsSource", () => {
  describe("listConversations (D3, D4)", () => {
    it("maps the wire ConversationPageResponse (snake_case) to ConversationList (camelCase), preserving the {items, total, page, per_page} envelope without total_pages", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [
          {
            id: "01",
            property_id: "p1",
            reservation_id: "r1",
            guest_id: "g1",
            channel: "WHATSAPP",
            status: "OPEN",
            escalation_status: "PENDING_HUMAN",
            language: "es",
            ai_enabled: true,
            last_message_at: "2026-08-22T10:00:00Z",
            created_at: "2026-08-22T09:00:00Z",
            updated_at: "2026-08-22T10:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        per_page: 20,
      });
      const source = new HttpConversationsSource(buildClient(request));

      const result = await source.listConversations("tenant-1");

      expect(result.items).toHaveLength(1);
      expect(result.items[0]).toEqual({
        id: "01",
        channel: "WHATSAPP",
        status: "OPEN",
        escalationStatus: "PENDING_HUMAN",
        lastMessageAt: "2026-08-22T10:00:00Z",
        createdAt: "2026-08-22T09:00:00Z",
      });
      expect(result.total).toBe(1);
      expect(result.page).toBe(1);
      expect(result.perPage).toBe(20);
      expect(result).not.toHaveProperty("totalPages");
      expect(result).not.toHaveProperty("total_pages");
    });

    it("translates camelCase filter keys to the wire snake_case (status, escalation_status, page, per_page)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 2,
        per_page: 20,
      });
      const source = new HttpConversationsSource(buildClient(request));

      await source.listConversations("tenant-1", {
        status: "OPEN",
        escalationStatus: "PENDING_HUMAN",
        page: 2,
        perPage: 20,
      });

      expect(request).toHaveBeenCalledWith("/api/v1/conversations", {
        query: {
          status: "OPEN",
          escalation_status: "PENDING_HUMAN",
          page: 2,
          per_page: 20,
        },
      });
    });

    it("does NOT add property_id under any branch (D4)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpConversationsSource(buildClient(request));

      await source.listConversations("tenant-1", {
        status: "OPEN",
        escalationStatus: "PENDING_HUMAN",
        page: 1,
        perPage: 20,
      });

      expect(request.mock.calls[0][1].query).not.toHaveProperty("property_id");
      expect(request.mock.calls[0][1].query).not.toHaveProperty("propertyId");
    });

    it("omits keys whose value is undefined (no extra keys on the wire)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpConversationsSource(buildClient(request));

      await source.listConversations("tenant-1", { escalationStatus: "PENDING_HUMAN" });

      expect(request.mock.calls[0][1].query).toEqual({
        escalation_status: "PENDING_HUMAN",
      });
    });

    it("emits an empty query when filters are empty (defaults belong to the backend)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        per_page: 20,
      });
      const source = new HttpConversationsSource(buildClient(request));

      await source.listConversations("tenant-1");

      expect(request).toHaveBeenCalledWith("/api/v1/conversations", { query: {} });
    });
  });

  describe("getConversation", () => {
    it("maps the wire ConversationResponse to ConversationDetailDto (all 13 fields in camelCase)", async () => {
      const request = vi.fn().mockResolvedValue({
        id: "01",
        property_id: "p1",
        reservation_id: null,
        guest_id: null,
        channel: "EMAIL",
        status: "ESCALATED",
        escalation_status: "HUMAN_HANDLING",
        language: "en",
        ai_enabled: false,
        last_message_at: null,
        created_at: "2026-08-22T09:00:00Z",
        updated_at: "2026-08-22T09:30:00Z",
      });
      const source = new HttpConversationsSource(buildClient(request));

      const result = await source.getConversation("tenant-1", "01");

      expect(result).toEqual({
        id: "01",
        propertyId: "p1",
        reservationId: null,
        guestId: null,
        channel: "EMAIL",
        status: "ESCALATED",
        escalationStatus: "HUMAN_HANDLING",
        language: "en",
        aiEnabled: false,
        lastMessageAt: null,
        createdAt: "2026-08-22T09:00:00Z",
        updatedAt: "2026-08-22T09:30:00Z",
      });
      expect(request).toHaveBeenCalledWith("/api/v1/conversations/{conversation_id}", {
        pathParams: { conversation_id: "01" },
      });
    });
  });

  describe("listMessages", () => {
    it("maps the wire MessagePageResponse to MessageList and discards metadata (closed audit keys, DTO §Data & interfaces)", async () => {
      const request = vi.fn().mockResolvedValue({
        items: [
          {
            id: "m1",
            conversation_id: "01",
            sender_type: "GUEST",
            sender_user_id: null,
            content: "Hola",
            language: "es",
            ai_generated: false,
            confidence_score: null,
            intent: null,
            metadata: { template_key: "x" },
            created_at: "2026-08-22T10:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        per_page: 20,
      });
      const source = new HttpConversationsSource(buildClient(request));

      const result = await source.listMessages("tenant-1", "01");

      expect(result.items).toHaveLength(1);
      expect(result.items[0]).toEqual({
        id: "m1",
        conversationId: "01",
        senderType: "GUEST",
        senderUserId: null,
        content: "Hola",
        language: "es",
        aiGenerated: false,
        confidenceScore: null,
        intent: null,
        createdAt: "2026-08-22T10:00:00Z",
      });
      expect(result.items[0]).not.toHaveProperty("metadata");
      expect(request).toHaveBeenCalledWith(
        "/api/v1/conversations/{conversation_id}/messages",
        { pathParams: { conversation_id: "01" }, query: { page: 1, per_page: 20 } },
      );
    });
  });

  describe("replyToConversation (D9)", () => {
    it("posts {content} only and never sends sender_type", async () => {
      const request = vi.fn().mockResolvedValue({
        id: "m1",
        conversation_id: "01",
        sender_type: "MANAGER",
        sender_user_id: "u1",
        content: "Hola",
        language: "es",
        ai_generated: false,
        confidence_score: null,
        intent: null,
        created_at: "2026-08-22T10:00:00Z",
      });
      const source = new HttpConversationsSource(buildClient(request));

      await source.replyToConversation("tenant-1", "01", { content: "Hola" });

      expect(request).toHaveBeenCalledWith(
        "/api/v1/conversations/{conversation_id}/messages",
        {
          method: "POST",
          pathParams: { conversation_id: "01" },
          body: { content: "Hola" },
        },
      );
      const calledOptions = request.mock.calls[0][1];
      expect(calledOptions.body).not.toHaveProperty("sender_type");
      expect(calledOptions.body).not.toHaveProperty("senderType");
    });
  });
});