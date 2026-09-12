# BLOCKED — tenant-settings-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Manual E2E browser check of /settings across roles

- **phase**: run
- **type**: deferred
- **tasks**: 6.4
- **what & why**: Task 6.4 requires a running stack and a browser to exercise TENANT_OWNER/PROPERTY_MANAGER/CLEANER/TECHNICIAN flows on /settings; auto has no browser access in this worktree run.
- **exact resume command**: /sdd:run tenant-settings-web 6.4

## /settings/integrations left exactly as-is (design D6)

- **phase**: design
- **type**: assumed
- **what & why**: The roadmap note (sdd/roadmap/tenant-settings-web.md, point 1) framed the disposition of /settings/integrations as a design-level call with no requirement forcing either direction: retire the sidebar route/placeholder, or leave it untouched. Design D6 took the reversible option — leave the route, its RoutePlaceholder, and its route-registry.ts entry exactly as they are today, since the roadmap note itself names future webhook-endpoint provisioning as a plausible future occupant, and doing nothing forecloses nothing while retiring it would be a separate, avoidable decision this change did not need to make. Rejected alternative: retire the route/sidebar entry now (not requested by any R#, and PMS-by-UI is out of scope per security rule 3(a) regardless).
- **exact resume command**: No action needed to proceed; delete this entry once you've read D6 in sdd/changes/tenant-settings-web/design.md and are satisfied with 'leave as-is' rather than retiring the route.
