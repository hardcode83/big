import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/lib/api";
import { HttpGuestPortalSource } from "./http-guest-portal-source";

const stay = { access_code_masked: null, address_line1: null, address_line2: null, arrival_notes: null, check_in_date: "2026-08-11", check_in_time: "15:00", check_out_date: "2026-08-12", check_out_time: "11:00", city: null, country: "ES", postal_code: null, property_name: "Casa", province: null, support_channel: null, timezone: "Europe/Madrid", wifi_name: null, extra: "ignored" };
const message = { id: "m1", sender: "GUEST", content: "Hola", created_at: "2026-08-30T10:00:00Z", intent: "leaked" };
const thread = { items: [message], total: 1, page: 1, per_page: 50, state: "AWAITING_HUMAN" };
const fakeClient = () => {
  const requests: Array<{ path: string; options?: Record<string, unknown> }> = [];
  const request = vi.fn(async (path: string, options?: Record<string, unknown>) => { requests.push({ path, options }); if (path.includes("info")) return stay; if (path.includes("incident")) return { id: "id", status: "OPEN", created_at: "2026-08-11T10:00:00Z" }; if (path.includes("messages")) return options?.method === "POST" ? message : thread; if (options?.method === "POST") return { document_status: "PROVIDED", legal_registration_status: "SUBMITTED" }; return { document_status: "NOT_PROVIDED", legal_registration_status: "PENDING_GUEST_DATA", missing_fields: ["full_name"] }; });
  return { client: { request } as unknown as ApiClient, requests, request };
};

describe("HttpGuestPortalSource security boundary", () => {
  it("uses exactly the allowed endpoints and emits no Authorization header", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    await source.getStayInfo("token-a"); await source.getCheckinStatus("token-a");
    await source.submitCheckin("token-a", { full_name: "A", nationality: "ES", date_of_birth: "1990-01-01", document_type: "DNI", document_number: "X", document_expiry_date: "2030-01-01" });
    await source.reportIncident("token-a", { title: "Leak", description: "Water" });
    await source.getConversation("token-a"); await source.postMessage("token-a", { content: "Hola" });
    expect(fake.requests.map((r) => r.path)).toEqual(["/api/v1/guest/info/{token}", "/api/v1/guest/checkin/{token}", "/api/v1/guest/checkin/{token}", "/api/v1/guest/incident/{token}", "/api/v1/guest/messages/{token}", "/api/v1/guest/messages/{token}"]);
    expect(fake.requests.every((r) => !(r.options?.headers as Record<string, string> | undefined)?.Authorization)).toBe(true);
  });

  it("sends only the published request fields and preserves null contract values", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    expect((await source.getStayInfo("a")).wifiName).toBeNull();
    await source.submitCheckin("a", { full_name: "A", nationality: "ES", date_of_birth: "1990-01-01", document_type: "DNI", document_number: "X", document_expiry_date: "2030-01-01" });
    await source.reportIncident("a", { title: "T", description: "D" });
    expect(fake.request.mock.calls[1][1]).toEqual(expect.objectContaining({ body: { full_name: "A", nationality: "ES", date_of_birth: "1990-01-01", document_type: "DNI", document_number: "X", document_expiry_date: "2030-01-01" } }));
    expect(fake.request.mock.calls[2][1]).toEqual(expect.objectContaining({ body: { title: "T", description: "D" } }));
  });
});

describe("guest security source constraints", () => {
  it("does not import or re-export authenticated-client / session interaction", async () => {
    const exports = await import("./http-guest-portal-source");
    expect(Object.keys(exports)).toEqual(["HttpGuestPortalSource"]);
    const src = readFileSync(join(process.cwd(), "features/guest-portal/data/http/http-guest-portal-source.ts"), "utf8");
    expect(src).not.toMatch(/authenticated-client|getSessionTokens|createAuthenticatedClients|session-store/);
  });
});

describe("the conversation methods (R5.9, R5.5, design D9)", () => {
  it("omits page unless asked for, so the backend answers the most recent window", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    await source.getConversation("token-a");
    expect((fake.request.mock.calls[0][1] as { query?: Record<string, unknown> }).query).toEqual({});
  });

  it("passes an explicit window through under the contract's own parameter names", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    await source.getConversation("token-a", { page: 2, perPage: 10 });
    expect((fake.request.mock.calls[0][1] as { query?: Record<string, unknown> }).query).toEqual({ page: 2, per_page: 10 });
  });

  it("sends only content when posting, never a sender or an id the backend forbids", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    await source.postMessage("token-a", { content: "Hola" });
    expect(fake.request.mock.calls[0][1]).toEqual(expect.objectContaining({ body: { content: "Hola" } }));
  });

  /**
   * The backend's projection has no `intent` field, so this cannot happen against the real API —
   * which is exactly why the fake returns one. What is pinned here is that the mapper carries
   * across the four published fields and nothing else, so a backend that regressed and started
   * leaking an internal field would not have it silently reach the component tree.
   */
  it("maps only the four published fields of a message", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    const conversation = await source.getConversation("token-a");
    expect(Object.keys(conversation.items[0]).sort()).toEqual(["content", "createdAt", "id", "sender"]);
  });

  it("carries the grouped sender and the thread state across without deriving anything", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    const conversation = await source.getConversation("token-a");
    expect(conversation.items[0].sender).toBe("GUEST");
    expect(conversation.state).toBe("AWAITING_HUMAN");
    expect(conversation.perPage).toBe(50);
  });
});
