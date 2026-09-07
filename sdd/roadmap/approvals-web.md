# approvals-web

[BE+FE] **la pantalla `/approvals`, hoy `RoutePlaceholder`, y la ruta de lista que necesita**.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04). Cierra el único callejón sin salida del ciclo del técnico que es alcanzable en
> uso normal.

**El hecho medido (2026-09-04)**: `frontend/app/(workspace)/approvals/page.tsx:11` es un
`RoutePlaceholder`. El `TENANT_OWNER` tiene `RESPOND_OWNER_APPROVALS`
(`backend/app/auth/domain/policy.py:343-383`) y es el **único** rol que lo tiene; la ruta de
respuesta existe (`backend/app/maintenance/api/approvals_router.py:39`) y **la de lista no
existe a propósito** (`approvals_router.py:3-8`). Hoy una aprobación pendiente sólo se *ve*
como id en el detalle de la propiedad
(`frontend/features/dashboard/components/detail/property-detail-sections.tsx:129-139`), sin
botón.

**Por qué no es cosmético**: hay dos compuertas de aprobación en `maintenance/application/use_cases.py`
—coste estimado (:1567) y coste final (:2174)— contra `owner_approval_threshold_eur`, default
`Decimal("100.00")` (`tenants/domain/entities.py:151`). Cualquier resolución que las cruce aparca
la incidencia en `AWAITING_OWNER_APPROVAL`, donde `frontend/features/tech/lib/tech-actions.ts:31`
ofrece —correctamente— cero acciones. El técnico no puede seguir, el manager no puede intervenir,
y el owner no tiene dónde responder: **un callejón sin salida que se alcanza en uso normal**
(DoD §28.12 pide que la aprobación se genere; PRD §12 «Regla de aprobación» pide que se responda).
Y el job `reconcile_owner_approvals_for_expenses` (cada 5 min, `scheduler/schedule.py:69`) sólo
tiene trabajo si alguien responde.

**Alcance**:

- **[BE]** una ruta de lista paginada de aprobaciones del tenant, filtrable por estado
  (pendientes por defecto), acotada por `tenant_id` del token como todo lo demás; y lo que el
  detalle necesite para que el owner decida sin abrir tres pantallas: incidencia, propiedad
  legible, coste, quién lo pide y desde cuándo. La ausencia de lista era deliberada cuando no
  había consumidor; esta entrada es el consumidor, así que el docstring de `approvals_router.py:3-8`
  se reescribe, no se ignora.
- **[FE]** `/approvals`: cola de pendientes con aprobar/rechazar y motivo, más un histórico
  corto. Misma forma que `pricing-web` (cola con decisión), que es el precedente de «pantalla
  cuyo valor es una mutación».

**Lo que decide y no es cosmético**:

1. **Qué ve el manager.** No tiene `RESPOND_OWNER_APPROVALS`; si la ruta de lista pide un permiso
   nuevo o reutiliza `READ_INCIDENTS`, cambia quién ve la cola. Recomendación: lectura para
   owner y manager (el manager necesita saber que está parado y por qué), respuesta sólo owner,
   y el botón gateado con `useHasPermission` como en `conversation-thread-view.tsx:56`.
2. **Qué pasa al aprobar.** La incidencia vuelve al técnico (`AWAITING_OWNER_APPROVAL → …`) y
   el técnico tiene que enterarse: `NOTIFICATION` al asignado existe como tipo —comprobar en
   `notification-writers-gap` si el escritor está—, y el deep-link para `technician` en
   `features/notifications/lib/notification-destinations.ts:37-39` **está vacío** aunque
   `/tech/incidents/[id]` ya existe; esta entrada lo rellena o lo declara.
3. **Notificar al owner** de que hay una aprobación pendiente ya lo hace el backend
   (`OWNER_APPROVAL_REQUESTED` o equivalente, medir); la campana ya está en las tres shells.
   Comprobar que el deep-link `workspace` lleva a `/approvals` y no a la incidencia.
4. **El motivo del rechazo** es texto libre de una persona sobre su propio ámbito (forma de la
   excepción 3 de la regla 11); si va a una columna nueva, `storable_text` como `materials`.

**Fuera de alcance**: cambiar el umbral (es `tenant-settings-web`); aprobación de gastos que no
vengan de una incidencia (`Expense` de `revenue-statements` tiene su propia vía, y
`reconcile_owner_approvals_for_expenses` ya la cose); notificación por WhatsApp/email al owner
más allá de lo que `notification-channel-routing` ya haga.

**Verificación que el change debe dejar hecha**: incidencia resuelta por el técnico con coste
final 150 € → aparece en `/approvals` del owner → aprobar → el técnico ve la incidencia
desbloqueada en `/tech` y la campana le lleva a ella.
