import type { components } from "@/lib/api/generated/openapi";

export type GuestDocumentType = components["schemas"]["GuestDocumentType"];
export type GuestDocumentStatus = components["schemas"]["GuestDocumentStatus"];
export type LegalRegistrationStatus = components["schemas"]["LegalRegistrationStatus"];
export type IncidentStatus = components["schemas"]["IncidentStatus"];

export namespace GuestPortalDTOs {
  export interface StayInfo { accessCodeMasked: string | null; addressLine1: string | null; addressLine2: string | null; arrivalNotes: string | null; checkInDate: string; checkInTime: string; checkOutDate: string; checkOutTime: string; city: string | null; country: string; postalCode: string | null; propertyName: string; province: string | null; supportChannel: string | null; timezone: string; wifiName: string | null; }
  export interface CheckinStatus { documentStatus: GuestDocumentStatus; legalRegistrationStatus: LegalRegistrationStatus; missingFields: string[]; }
  export interface SubmitCheckin { full_name: string; nationality: string; date_of_birth: string; document_type: GuestDocumentType; document_number: string; document_expiry_date: string; }
  export interface CheckinSubmitted { documentStatus: GuestDocumentStatus; legalRegistrationStatus: LegalRegistrationStatus; }
  export interface ReportIncident { title: string; description: string; }
  export interface IncidentReported { id: string; status: IncidentStatus; createdAt: string; }
}
