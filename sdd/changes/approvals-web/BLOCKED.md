# BLOCKED — approvals-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Technician-side half of the manual E2E pass (task 8.6) not done

- **phase**: review
- **type**: deferred
- **tasks**: 8.6
- **what & why**: The owner-side half was verified live (queue, approve/reject, history, bell to /approvals, property-detail link — see tasks.md's section-8 notes). The technician-side half (does /tech show the incident unblocked, does the bell link to /tech/incidents/{id}) was blocked by host-wide memory contention crash-looping the frontend container. It is covered at the integration level by test_approving_notifies_the_assigned_technician/test_rejecting_notifies_the_assigned_technician (real DB) plus notification-destinations.test.ts's technician+incident case, but the literal browser walk is outstanding.
- **exact resume command**: make up PORT_OFFSET=<n> when the host has headroom; log in as technician@demo.local (password in .env), open /tech, confirm the REDES11 incident (or a fresh one from make seed-demo) shows unblocked with the outcome notification linking to /tech/incidents/{id}; then check task 8.6 in tasks.md.
