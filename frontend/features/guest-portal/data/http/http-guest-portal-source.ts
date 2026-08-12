import type { ApiClient } from "@/lib/api";
import type { components } from "@/lib/api/generated/openapi";
import type { GuestPortalDataSource } from "../guest-portal-source";
import type { GuestPortalDTOs } from "../dto";

type Stay = components["schemas"]["StayInfoResponse"];
type Checkin = components["schemas"]["CheckinStatusResponse"];
type Submitted = components["schemas"]["CheckinSubmittedResponse"];
type Incident = components["schemas"]["IncidentReportedResponse"];

const mapStay = (v: Stay): GuestPortalDTOs.StayInfo => ({ accessCodeMasked: v.access_code_masked, addressLine1: v.address_line1, addressLine2: v.address_line2, arrivalNotes: v.arrival_notes, checkInDate: v.check_in_date, checkInTime: v.check_in_time, checkOutDate: v.check_out_date, checkOutTime: v.check_out_time, city: v.city, country: v.country, postalCode: v.postal_code, propertyName: v.property_name, province: v.province, supportChannel: v.support_channel, timezone: v.timezone, wifiName: v.wifi_name });
const mapCheckin = (v: Checkin): GuestPortalDTOs.CheckinStatus => ({ documentStatus: v.document_status, legalRegistrationStatus: v.legal_registration_status, missingFields: v.missing_fields });
const mapSubmitted = (v: Submitted): GuestPortalDTOs.CheckinSubmitted => ({ documentStatus: v.document_status, legalRegistrationStatus: v.legal_registration_status });
const mapIncident = (v: Incident): GuestPortalDTOs.IncidentReported => ({ id: v.id, status: v.status, createdAt: v.created_at });

export class HttpGuestPortalSource implements GuestPortalDataSource {
  constructor(private readonly client: ApiClient) {}
  async getStayInfo(token: string) { return mapStay(await this.client.request("/api/v1/guest/info/{token}", { pathParams: { token } })); }
  async getCheckinStatus(token: string) { const response = await this.client.request("/api/v1/guest/checkin/{token}", { method: "GET", pathParams: { token } }); return mapCheckin(response as Checkin); }
  async submitCheckin(token: string, data: GuestPortalDTOs.SubmitCheckin) { return mapSubmitted(await this.client.request("/api/v1/guest/checkin/{token}", { method: "POST", pathParams: { token }, body: data })); }
  async reportIncident(token: string, data: GuestPortalDTOs.ReportIncident) { return mapIncident(await this.client.request("/api/v1/guest/incident/{token}", { method: "POST", pathParams: { token }, body: data })); }
}
