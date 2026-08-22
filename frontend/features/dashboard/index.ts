// Public API of the dashboard feature (design D2). app/ composes these entry
// points; internals (data source, hooks, cards, detail sections) stay private.
export { DashboardView } from "./components/dashboard-view";
export { PropertyDetailView } from "./components/detail/property-detail-view";
// `PropertyTimeline` stays internal on purpose (OQ1): `/timeline` mounts it through
// `TimelineView`, so exporting it too would be public API nothing imports.
export { TimelineView } from "./components/timeline/timeline-view";
