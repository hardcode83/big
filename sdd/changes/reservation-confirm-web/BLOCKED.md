# BLOCKED — reservation-confirm-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## paymentStatus editable en canales no manuales

- **phase**: design
- **type**: assumed
- **what & why**: La nota del roadmap (`sdd/roadmap/reservation-confirm-web.md`) recomienda editable para anotar la señal cobrada en canal directo y deja la cuestión abierta para canales OTA. D4 toma la opción recomendada: `paymentStatus` no entra en `INGEST_OWNED_FIELDS` y queda editable para todos los canales. Alternativas consideradas: (a) mover `paymentStatus` a `INGEST_OWNED_FIELDS` y deshabilitarlo en canales OTA — requiere coordinarse con `pms-ingest-change-events`, fuera de alcance; (b) ofrecer `payment_status` solo en reservas CONFIRMED — el proposal R2.3 lo prohíbe (no es gate). Materializado en design.md D4 + bloque `paymentStatus` en `EDITABLE_FIELDS` (`frontend/features/reservations/components/edit/edit-reservation-form.tsx`).
- **exact resume command**: /sdd:design reservation-confirm-web (sólo si se quiere vetar la decisión; la implementación ya respeta la opción tomada)
