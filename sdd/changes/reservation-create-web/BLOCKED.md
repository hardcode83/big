# BLOCKED — reservation-create-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Auto bloqueado por límite semanal del runtime

- **phase**: auto
- **type**: deferred
- **what & why**: La receta oficial sdd_auto_outcome.py falló dos veces antes de iniciar cualquier fase por límite semanal de API; el runtime indica reset el 14 de septiembre a las 00:00 Europe/Madrid. No hay design, tasks ni implementación generados por auto.
- **exact resume command**: /sdd:auto reservation-create-web

## 6.5 Browser create/edit/cancel flow

- **phase**: run
- **type**: deferred
- **tasks**: 6.5
- **what & why**: Manual browser verification requires a running app plus manager/owner accounts and a mutation error path; this environment has no authenticated browser session.
- **exact resume command**: /sdd:run reservation-create-web 6.5

## Resolver findings adicionales de contrato y accesibilidad

- **phase**: review
- **type**: decision
- **what & why**: Los blockers solicitados ya están resueltos: mutation.errors.cancel.network es la clave válida número 177, la aserción pasa, README usa reservation-create-web y la suite completa pasa (240 archivos, 2717 tests). El panel final, sin embargo, detecta findings nuevos fuera del scope pedido: edit-reservation-form.tsx:73 permite fechas iguales mientras backend/app/reservations/domain/entities.py rechaza check_out_date <= check_in_date (R2.3/D5); reservation-detail-view.tsx:55 deja enlaces de vuelta sin objetivo táctil 44x44; edit-reservation-form.tsx:136 no asocia aria-describedby a la explicación de campos deshabilitados; y create-reservation-form.test.tsx:167 no cubre keyboard/focus, contraste ni clipping responsive. No se han cambiado porque la instrucción fue no ampliar scope. Resolver estos findings antes de certificar.
- **exact resume command**: /sdd:auto reservation-create-web
