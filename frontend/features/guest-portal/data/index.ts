import { createApiClient } from "@/lib/api";
import { HttpGuestPortalSource } from "./http/http-guest-portal-source";
export type { GuestPortalDataSource } from "./guest-portal-source";
export type { GuestPortalDTOs, GuestDocumentType, GuestDocumentStatus, LegalRegistrationStatus, IncidentStatus } from "./dto";
const guestPortalDataSource = new HttpGuestPortalSource(createApiClient({ baseUrl: "" }));
export function getGuestPortalDataSource() { return guestPortalDataSource; }
