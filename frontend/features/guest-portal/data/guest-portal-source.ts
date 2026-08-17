import type { GuestPortalDTOs } from "./dto";

export interface GuestPortalDataSource {
  getStayInfo(token: string): Promise<GuestPortalDTOs.StayInfo>;
  getCheckinStatus(token: string): Promise<GuestPortalDTOs.CheckinStatus>;
  submitCheckin(token: string, data: GuestPortalDTOs.SubmitCheckin): Promise<GuestPortalDTOs.CheckinSubmitted>;
  reportIncident(token: string, data: GuestPortalDTOs.ReportIncident): Promise<GuestPortalDTOs.IncidentReported>;
}
