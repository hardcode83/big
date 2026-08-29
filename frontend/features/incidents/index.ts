// Barrel for the incidents feature. The App Router pages import the two
// view components from here; the data layer and the hooks are also
// re-exported so a single `@/features/incidents` import brings the whole
// feature into scope.
export { IncidentsView } from "./components/list/incidents-view";
export { IncidentsFilters } from "./components/list/incidents-filters";
export { IncidentDetailView } from "./components/detail/incident-detail-view";
export {
  useIncidents,
  useIncidentsPages,
  useIncident,
  useIncidentContext,
  useIncidentContexts,
  useIncidentPhotos,
  type IncidentsPagesResult,
} from "./hooks/use-incidents";
export {
  useIncidentCycleAction,
  useResolveIncident,
  useUploadIncidentPhoto,
  type IncidentCycleAction,
  type IncidentCycleInput,
  type IncidentCycleOptions,
  type ResolveIncidentVariables,
  type UploadIncidentPhotoVariables,
} from "./hooks/use-incident-cycle";
export { incidentsKeys } from "./hooks/query-keys";
export { mapIncidentsError } from "./lib/error-mapping";
export { conflictReason, type ConflictReason } from "./lib/conflict-reason";
export { severityColorGroup } from "./lib/severity-tone";
export { getIncidentsDataSource } from "./data";
export type * from "./data";