import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";
import type { GuestPortalDataSource } from "../guest-portal-source";
import type { GuestPortalDTOs } from "../dto";

type Stay = components["schemas"]["StayInfoResponse"];
type Checkin = components["schemas"]["CheckinStatusResponse"];
type Submitted = components["schemas"]["CheckinSubmittedResponse"];
type Incident = components["schemas"]["IncidentReportedResponse"];
type Thread = components["schemas"]["GuestThreadResponse"];
type ThreadMessage = components["schemas"]["GuestMessageResponse"];

const mapStay = (v: Stay): GuestPortalDTOs.StayInfo => ({ accessCodeMasked: v.access_code_masked, addressLine1: v.address_line1, addressLine2: v.address_line2, arrivalNotes: v.arrival_notes, checkInDate: v.check_in_date, checkInTime: v.check_in_time, checkOutDate: v.check_out_date, checkOutTime: v.check_out_time, city: v.city, country: v.country, postalCode: v.postal_code, propertyName: v.property_name, province: v.province, supportChannel: v.support_channel, timezone: v.timezone, wifiName: v.wifi_name });
const mapCheckin = (v: Checkin): GuestPortalDTOs.CheckinStatus => ({ documentStatus: v.document_status, legalRegistrationStatus: v.legal_registration_status, missingFields: v.missing_fields });
const mapSubmitted = (v: Submitted): GuestPortalDTOs.CheckinSubmitted => ({ documentStatus: v.document_status, legalRegistrationStatus: v.legal_registration_status });
const mapIncident = (v: Incident): GuestPortalDTOs.IncidentReported => ({ id: v.id, status: v.status, createdAt: v.created_at });
// Field for field, and nothing derived: `sender` is carried across as the backend grouped it
// (R5.5 forbids deriving the AI/person distinction here), and there is no field to drop
// because the published projection has none to begin with.
const mapMessage = (v: ThreadMessage): GuestPortalDTOs.ConversationMessage => ({ id: v.id, sender: v.sender, content: v.content, createdAt: v.created_at });
const mapThread = (v: Thread): GuestPortalDTOs.Conversation => ({ items: v.items.map(mapMessage), total: v.total, page: v.page, perPage: v.per_page, state: v.state });

export class HttpGuestPortalSource implements GuestPortalDataSource {
  constructor(private readonly client: ApiClient) {}
  async getStayInfo(token: string) { return mapStay(await this.client.request("/api/v1/guest/info/{token}", { pathParams: { token } })); }
  async getCheckinStatus(token: string) { const response = await this.client.request("/api/v1/guest/checkin/{token}", { method: "GET", pathParams: { token } }); return mapCheckin(response as Checkin); }
  async submitCheckin(token: string, data: GuestPortalDTOs.SubmitCheckin) { return mapSubmitted(await this.client.request("/api/v1/guest/checkin/{token}", { method: "POST", pathParams: { token }, body: data })); }
  async reportIncident(token: string, data: GuestPortalDTOs.ReportIncident) { return mapIncident(await this.client.request("/api/v1/guest/incident/{token}", { method: "POST", pathParams: { token }, body: data })); }
  // `page` is omitted unless asked for: the backend answers the **last** window when it is
  // absent, which is where a thread is read from. Sending `page=1` by default would open
  // every conversation at its oldest message and cost a second round trip on every poll.
  async getConversation(token: string, params: { page?: number; perPage?: number } = {}) { const response = await this.client.request("/api/v1/guest/messages/{token}", { method: "GET", pathParams: { token }, query: { ...(params.page === undefined ? {} : { page: params.page }), ...(params.perPage === undefined ? {} : { per_page: params.perPage }) } }); return mapThread(response as Thread); }
  async postMessage(token: string, data: GuestPortalDTOs.PostMessage) { return mapMessage(await this.client.request("/api/v1/guest/messages/{token}", { method: "POST", pathParams: { token }, body: data })); }
}
