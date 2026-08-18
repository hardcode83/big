import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/lib/api";
import { HttpGuestPortalSource } from "./http-guest-portal-source";

const stay = { access_code_masked: null, address_line1: null, address_line2: null, arrival_notes: null, check_in_date: "2026-08-11", check_in_time: "15:00", check_out_date: "2026-08-12", check_out_time: "11:00", city: null, country: "ES", postal_code: null, property_name: "Casa", province: null, support_channel: null, timezone: "Europe/Madrid", wifi_name: null, extra: "ignored" };
const fakeClient = () => {
  const requests: Array<{ path: string; options?: Record<string, unknown> }> = [];
  const request = vi.fn(async (path: string, options?: Record<string, unknown>) => { requests.push({ path, options }); if (path.includes("info")) return stay; if (path.includes("incident")) return { id: "id", status: "OPEN", created_at: "2026-08-11T10:00:00Z" }; if (options?.method === "POST") return { document_status: "PROVIDED", legal_registration_status: "SUBMITTED" }; return { document_status: "NOT_PROVIDED", legal_registration_status: "PENDING_GUEST_DATA", missing_fields: ["full_name"] }; });
  return { client: { request } as unknown as ApiClient, requests, request };
};

describe("HttpGuestPortalSource security boundary", () => {
  it("uses exactly the four allowed endpoints and emits no Authorization header", async () => {
    const fake = fakeClient(); const source = new HttpGuestPortalSource(fake.client);
    await source.getStayInfo("token-a"); await source.getCheckinStatus("token-a");
    await source.submitCheckin("token-a", { full_name: "A", nationality: "ES", date_of_birth: "1990-01-01", document_type: "DNI", document_number: "X", document_expiry_date: "2030-01-01" });
    await source.reportIncident("token-a", { title: "Leak", description: "Water" });
    expect(fake.requests.map((r) => r.path)).toEqual(["/api/v1/guest/info/{token}", "/api/v1/guest/checkin/{token}", "/api/v1/guest/checkin/{token}", "/api/v1/guest/incident/{token}"]);
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
