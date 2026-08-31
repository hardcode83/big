import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api";

import { HttpNotificationsSource } from "./http-notifications-source";

function buildClient(impl: ReturnType<typeof vi.fn>): ApiClient {
  return { request: impl } as unknown as ApiClient;
}

const WIRE_ROW = {
  id: "n1",
  notification_type: "CLEANING_TASK_ASSIGNED",
  channel: "IN_APP",
  status: "SENT",
  subject: "A cleaning task has been assigned to you.",
  body: "Task 5f1b…, property 9c2a…",
  related_type: "cleaning_task",
  related_id: "task-1",
  sent_at: "2026-08-29T08:00:00Z",
  created_at: "2026-08-29T08:00:00Z",
  read_at: null,
};

describe("HttpNotificationsSource", () => {
  describe("listNotifications", () => {
    it("maps the PRD §23 envelope to camelCase, including read_at → readAt", async () => {
      const request = vi.fn().mockResolvedValue({
        data: [WIRE_ROW, { ...WIRE_ROW, id: "n2", read_at: "2026-08-29T09:00:00Z" }],
        total: 2,
        page: 1,
        per_page: 20,
        total_pages: 1,
      });
      const source = new HttpNotificationsSource(buildClient(request));

      const result = await source.listNotifications("tenant-1");

      expect(request).toHaveBeenCalledWith("/api/v1/notifications", { query: {} });
      expect(result).toEqual({
        items: [
          {
            id: "n1",
            type: "CLEANING_TASK_ASSIGNED",
            relatedType: "cleaning_task",
            relatedId: "task-1",
            createdAt: "2026-08-29T08:00:00Z",
            readAt: null,
          },
          {
            id: "n2",
            type: "CLEANING_TASK_ASSIGNED",
            relatedType: "cleaning_task",
            relatedId: "task-1",
            createdAt: "2026-08-29T08:00:00Z",
            readAt: "2026-08-29T09:00:00Z",
          },
        ],
        total: 2,
        page: 1,
        perPage: 20,
        totalPages: 1,
      });
    });

    it("never carries subject or body into the DTO (R4.2)", async () => {
      const request = vi.fn().mockResolvedValue({
        data: [WIRE_ROW],
        total: 1,
        page: 1,
        per_page: 20,
        total_pages: 1,
      });
      const source = new HttpNotificationsSource(buildClient(request));

      const [row] = (await source.listNotifications("tenant-1")).items;

      expect(row).not.toHaveProperty("subject");
      expect(row).not.toHaveProperty("body");
      expect(JSON.stringify(row)).not.toContain("assigned to you");
    });

    it("sends page and per_page, and omits a filter that is undefined", async () => {
      const request = vi.fn().mockResolvedValue({
        data: [],
        total: 0,
        page: 2,
        per_page: 5,
        total_pages: 0,
      });
      const source = new HttpNotificationsSource(buildClient(request));

      await source.listNotifications("tenant-1", { page: 2, perPage: 5 });

      expect(request).toHaveBeenCalledWith("/api/v1/notifications", {
        query: { page: 2, per_page: 5 },
      });
    });

    it("sends unread=true only when asked, because absent and false mean the same thing (D5)", async () => {
      const payload = { data: [], total: 0, page: 1, per_page: 20, total_pages: 0 };
      const request = vi.fn().mockResolvedValue(payload);
      const source = new HttpNotificationsSource(buildClient(request));

      await source.listNotifications("tenant-1", { unread: true });
      expect(request).toHaveBeenLastCalledWith("/api/v1/notifications", {
        query: { unread: true },
      });

      await source.listNotifications("tenant-1", { unread: false });
      expect(request).toHaveBeenLastCalledWith("/api/v1/notifications", { query: {} });
    });
  });

  describe("countUnread", () => {
    it("asks the counter route and returns the number", async () => {
      const request = vi.fn().mockResolvedValue({ unread: 7 });
      const source = new HttpNotificationsSource(buildClient(request));

      await expect(source.countUnread("tenant-1")).resolves.toBe(7);
      expect(request).toHaveBeenCalledWith("/api/v1/notifications/unread-count");
    });
  });

  describe("markRead", () => {
    it("POSTs the acknowledgement with the id as a path parameter", async () => {
      const request = vi.fn().mockResolvedValue(undefined);
      const source = new HttpNotificationsSource(buildClient(request));

      await source.markRead("tenant-1", "n1");

      expect(request).toHaveBeenCalledWith(
        "/api/v1/notifications/{notification_id}/read",
        { method: "POST", pathParams: { notification_id: "n1" } },
      );
    });

    it("lets the client's error travel, so the mapper can turn it into a key", async () => {
      const failure = new Error("boom");
      const request = vi.fn().mockRejectedValue(failure);
      const source = new HttpNotificationsSource(buildClient(request));

      await expect(source.markRead("tenant-1", "n1")).rejects.toBe(failure);
    });
  });

  describe("markAllRead", () => {
    it("POSTs read-all and returns how many rows moved", async () => {
      const request = vi.fn().mockResolvedValue({ updated: 3 });
      const source = new HttpNotificationsSource(buildClient(request));

      await expect(source.markAllRead("tenant-1")).resolves.toBe(3);
      expect(request).toHaveBeenCalledWith("/api/v1/notifications/read-all", {
        method: "POST",
      });
    });

    it("returns zero without complaining on an inbox already up to date (D6)", async () => {
      const request = vi.fn().mockResolvedValue({ updated: 0 });
      const source = new HttpNotificationsSource(buildClient(request));

      await expect(source.markAllRead("tenant-1")).resolves.toBe(0);
    });
  });
});
