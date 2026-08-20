// Barrel for the incidents feature. The App Router pages import the two
// view components from here; the data layer and the hooks are also
// re-exported so a single `@/features/incidents` import brings the whole
// feature into scope.
export { IncidentsView } from "./components/list/incidents-view";
export { IncidentsFilters } from "./components/list/incidents-filters";
export { IncidentDetailView } from "./components/detail/incident-detail-view";
export { useIncidents, useIncident } from "./hooks/use-incidents";
export { incidentsKeys } from "./hooks/query-keys";
export { mapIncidentsError } from "./lib/error-mapping";
export { getIncidentsDataSource } from "./data";
export type * from "./data";