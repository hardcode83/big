# Proposal: tech-incident-context

## Why

El técnico recibe una incidencia asignada y no puede saber **a qué piso va ni cómo entra**.
`IncidentResponse` le devuelve `property_id` como UUID pelado, y el rol `TECHNICIAN` tiene
exactamente cinco permisos (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`, `READ_OWN_NOTIFICATIONS`,
`READ_INCIDENTS`, `EXECUTE_INCIDENTS`, en `backend/app/auth/domain/policy.py`), así que
propiedades, dashboard, timeline y reservas le contestan `403`. PRD §12 «UI del técnico» pide
dirección de la propiedad, instrucciones de contacto/acceso y notas del propietario/manager: tres
de las once cosas que enumera, y las tres sin fuente hoy.

La alternativa barata —concederle `READ_PROPERTIES`— queda descartada por lo mismo que la descartó
[`cleaner-task-context`](../../specs/cleaner-task-context.md): abriría el CRUD entero de
propiedades para resolver un nombre y una dirección.

Esta entrada salió de partir `tech-app` el 2026-08-19, porque una entrada `[FE]` cuyo rol no puede
llamar lo que la pantalla muestra no es implementable. El censo entero de PRD §12 contra el backend
entregado está en [`sdd/roadmap/tech-app.md`](../../roadmap/tech-app.md), y es la fuente de esta
propuesta junto al PRD.

## What changes

Una **proyección de solo lectura acotada a la incidencia asignada al llamante**,
`GET /api/v1/incidents/{incident_id}/context`, calcada de `cleaner-task-context`: identificación y
dirección postal de la propiedad, su `timezone`, sus **instrucciones de acceso**
(`properties.access_notes`) y la **nota que el manager escribe al asignar** — una columna nueva de
`Incident` que hoy no existe y que es la fuente que PRD §12 da por supuesta para «notas del
propietario/manager». El acotamiento por fila es el `restrict_to_technician_id` derivado del token
que `maintenance` R8/D13 ya usa, nunca un campo de la petición.

Exponer `access_notes` a un rol que hoy no la lee es lo que **dispara la decisión de steering
aparcada** sobre la regla 11 de `sdd/steering/security.md`: esa columna no está en la tabla de
sumideros de texto en claro, y este change la mete con su forma decidida. `cleaner-task-context`
dejó escrito por qué a él no le tocaba («esta proyección no lee ninguna de las cuatro»); aquí sí.

## Requirements

### R1 — La proyección: a qué propiedad va el técnico

**As a** técnico con una incidencia asignada, **I want** ver la identificación y la dirección
postal de la vivienda, **so that** pueda presentarme allí sin llamar al manager.

Acceptance criteria:

1. WHEN se solicita `GET /api/v1/incidents/{incident_id}/context` sobre una incidencia alcanzable
   por el llamante, THE SYSTEM SHALL devolver `200` con `property_name`, `property_internal_code` y
   los campos de dirección postal de la propiedad (`address_line1`, `address_line2`, `city`,
   `province`, `postal_code`, `country`).
2. THE SYSTEM SHALL incluir el `timezone` de la propiedad.
3. IF un campo de la respuesta es `NULL` en origen, THEN THE SYSTEM SHALL devolverlo como `null`
   **con su clave**, y no omitirla, verificado contra el cuerpo serializado y no dado por hecho.
4. THE SYSTEM SHALL devolver un conjunto de campos **cerrado y fijado por un test propio**, de modo
   que añadir uno sea un acto deliberado y no una deriva.
5. IF el `property_id` de la incidencia no resuelve dentro del tenant, THEN THE SYSTEM SHALL
   responder `404` (ver R4) y NEVER SHALL devolver una respuesta parcial: la propiedad alimenta la
   mayoría de los campos, así que sin ella no hay contexto que dar.

### R2 — Instrucciones de acceso, y la fila que le falta a la regla 11

**As a** técnico, **I want** leer las instrucciones de contacto y acceso de la vivienda, **so
that** pueda entrar sin depender de que alguien me abra.

Acceptance criteria:

1. THE SYSTEM SHALL incluir en la respuesta el `access_notes` de la propiedad, que es lo que PRD
   §12 pide como «instrucciones de contacto/acceso».
2. WHEN este change se archive, THE SYSTEM SHALL tener declarada la columna
   `properties.access_notes` en la tabla de sumideros de texto en claro de
   `sdd/steering/security.md` (regla 11), con su forma y su escritor, aprobada en el design como la
   propia regla exige.
3. THE SYSTEM SHALL decidir en el design la **forma** de esa columna entre las que la regla admite
   —cifrado en reposo, exclusión de los listados, o ambas— y SHALL implementar la decidida, no
   solo documentarla.
4. THE SYSTEM SHALL dejar escrito, en la spec de esta capacidad, **por qué no** cubre a la vez
   `properties.cleaning_notes`, `properties.emergency_notes` ni `access_records.notes`: esta
   proyección no lee ninguna de las tres, así que ninguna crece de lectores aquí.
   `sdd/roadmap/cleaner-app.md` pide cubrir las cuatro juntas o decir explícitamente por qué no —
   esto es el «por qué no», y deja las otras tres donde están.
5. THE SYSTEM NEVER SHALL exponer `wifi_password_encrypted` ni `has_wifi_password` por esta ruta
   (R5).

### R3 — La nota del manager, que hoy no tiene columna

**As a** manager que asigna una incidencia, **I want** dejarle al técnico una nota junto con la
asignación, **so that** llegue sabiendo lo que el ticket no cuenta.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a `Incident` una columna de texto libre, opcional y acotada en longitud,
   para la nota que el manager escribe al asignar, con su migración de Alembic.
2. WHEN se llama `POST /api/v1/incidents/{incident_id}/assign`, THE SYSTEM SHALL aceptar esa nota
   como campo **opcional** del cuerpo, manteniendo `extra="forbid"` y sin cambiar el permiso
   (`MANAGE_INCIDENTS`) ni la tabla de transiciones de `maintenance` R1.
3. THE SYSTEM SHALL devolver esa nota en la proyección de R1, y NEVER SHALL añadirla a
   `IncidentResponse`: el listado paginado no la necesita y el contrato de incidencia no cambia.
4. WHEN este change se archive, THE SYSTEM SHALL tener declarada esa columna en la tabla de
   sumideros de la regla 11 con su escritor —una persona autenticada que teclea prosa propia— y su
   excepción, siguiendo el precedente de `owner_approvals.response_notes`.
5. THE SYSTEM SHALL mantener la nota **fuera** de `AUDITABLE_FIELDS` de `INCIDENT` (`maintenance`
   R9 audita once campos), y esa exclusión SHALL ser **estructural** como la de
   `title`/`description`: nombrarla en un `ChangeSet` levanta error, no pasa desapercibida.
6. THE SYSTEM SHALL escribir el `AuditLog` y el `TimelineEvent` de la asignación como hoy, sin que
   el texto de la nota viaje al timeline: metadatos que son solo identificadores.

### R4 — Acotamiento por fila, autorización y un `404` que no es sonda

**As a** responsable de seguridad, **I want** que esta ruta no amplíe lo que el técnico ya podía
ver ni sirva para averiguar qué existe, **so that** abrir la app del técnico no abra el tenant.

Acceptance criteria:

1. THE SYSTEM SHALL exigir `READ_INCIDENTS` en la puerta y responder `403` antes de tocar la base
   de datos cuando el llamante no lo tiene. NEVER SHALL crear un permiso nuevo: lo tendrían
   exactamente los roles que ya tienen éste.
2. WHILE el llamante tiene rol `TECHNICIAN`, THE SYSTEM SHALL restringir la consulta a las
   incidencias cuyo `assigned_technician_id` sea el suyo, derivado del **rol persistido** que se
   relee del usuario en cada petición (`IncidentActor.restrict_to_technician_id`, `maintenance`
   D13), y NEVER SHALL aceptar ni ensanchar esa restricción desde la petición.
3. WHILE el llamante tiene rol `PROPERTY_MANAGER` o `TENANT_OWNER`, THE SYSTEM SHALL devolver el
   contexto de cualquier incidencia de su tenant.
4. IF la incidencia no existe, pertenece a otro tenant, está asignada a otro técnico, o su
   `property_id` no resuelve dentro del tenant, THEN THE SYSTEM SHALL responder `404 NOT_FOUND` con
   un cuerpo **idéntico** en los cuatro casos.
5. THE SYSTEM SHALL tomar el `tenant_id` únicamente del token verificado y pasarlo explícito a cada
   lectura de repositorio, y NEVER SHALL aceptarlo en ningún esquema de petición.
6. THE SYSTEM SHALL demostrar el cruce de tenant con tests propios, incluida la incidencia que
   apunta a la propiedad de otro tenant.
7. THE SYSTEM NEVER SHALL exponer esta ruta al rol `CLEANER` ni al portador de un token de huésped.

### R5 — Lo que la proyección nunca lleva

**As a** quien añada un campo aquí mañana, **I want** que la exclusión sea estructural y no una
promesa, **so that** un `from_attributes` no filtre lo que un permiso guarda.

Acceptance criteria:

1. THE SYSTEM SHALL construir la respuesta desde un **dataclass congelado del dominio** espejado
   campo a campo en el contrato, y NEVER SHALL serializar una entidad `Property` ni `Reservation`.
2. THE SYSTEM NEVER SHALL incluir `wifi_password_encrypted`, `has_wifi_password`,
   `cleaning_notes` ni `emergency_notes`.
3. THE SYSTEM NEVER SHALL incluir ningún campo de reserva: importe bruto, comisión, importe neto,
   estado de pago, canal, `guest_id`, `special_requests` ni `internal_notes`. PRD §12 no pide la
   reserva en esta pantalla.
4. THE SYSTEM NEVER SHALL incluir `reported_by_guest_token`, `reported_by_user_id` ni
   `ai_classification`, que `maintenance` R8 ya excluye del contrato de incidencia.
5. THE SYSTEM SHALL respetar la regla de `cleaner-task-context`: **una proyección puede estrechar,
   nunca unir**. Un campo que un permiso guarda como un todo no entra aquí sin pasar por la
   decisión D10 de [`dashboard-api`](../../specs/dashboard-api.md).

### R6 — Contrato publicado

**As a** el frontend que va a consumir esto en `tech-app`, **I want** el contrato generado y
commiteado, **so that** la pantalla se escriba contra tipos y no contra suposiciones.

Acceptance criteria:

1. THE SYSTEM SHALL declarar la operación en `backend/openapi.json` con su esquema de respuesta
   enumerado campo a campo, y SHALL mantener regenerado y commiteado
   `frontend/lib/api/generated/openapi.d.ts` en el mismo PR
   ([`api-contract.md`](../../specs/api-contract.md), `steering/documentation.md`).
2. THE SYSTEM SHALL declarar su `404` en la propia ruta con el sobre de error de PRD §23 y el
   código `NOT_FOUND`, con un `responses=` per-endpoint.
3. THE SYSTEM SHALL documentar en la `description` de la operación que el conjunto de incidencias
   visibles depende del **rol persistido del token** y no es ensanchable por parámetro, y qué
   significa cada `null`.
4. THE SYSTEM SHALL reflejar en el contrato el campo opcional que R3 añade a `assign`.

## Out of scope

- **La UI del técnico.** `/tech` y `/tech/incidents/[id]` los implementa `tech-app`, que ya declara
  esta entrada en su `needs`. El andamio (`frontend/app/(field)/tech/`, `TechnicianShell`,
  `AuthGuard`) ya existe y no se toca aquí.
- **Fotos de la incidencia.** Entidad, rutas y el par antes/después son de `incident-photos`.
- **`reject`, ETA, materiales y «en ruta».** Son de `tech-cycle-completion`, que es quien toca la
  tabla de transiciones de `maintenance` R1 y decide si `TECHNICIAN_EN_ROUTE` es estado nuevo o si
  `start` pasa a significarlo.
- **`access_records.notes`, `properties.cleaning_notes` y `properties.emergency_notes`.** Ninguna se
  lee aquí (R2.4). La primera sigue siendo de `cleaner-app`.
- **Conceder `READ_PROPERTIES` o `READ_RESERVATIONS` a `TECHNICIAN`.** El conjunto de permisos del
  rol no cambia.
- **El contexto embebido en el listado.** `IncidentPageResponse` no lo lleva; lo decidirá `tech-app`
  con una pantalla real delante, y con 2 viviendas en el MVP N es pequeño.
- **El umbral de aprobación del propietario.** Lo resuelve `maintenance` R4 en su segunda puerta; la
  app lo muestra, no lo calcula.
- **Una ruta de creación de incidencias.** `maintenance` R8 la niega explícitamente y esa negativa
  sobrevive a este change.

## Affected specs

- `sdd/specs/tech-incident-context.md` — *(no existe aún — se creará al archivar)*
- `sdd/specs/maintenance.md` — R8 gana una ruta (de doce a trece) y el campo opcional de `assign`;
  R9 gana la exclusión estructural de la nota nueva.
- `sdd/specs/properties-crud.md` — `access_notes` cambia de audiencia y de forma (R2.3).
- `sdd/specs/api-contract.md` — la operación nueva en los dos artefactos del puente.
- `sdd/steering/security.md` — dos filas nuevas en la tabla de sumideros de la regla 11
  (`properties.access_notes` y la columna de R3). Es steering, no spec, pero es donde vive el
  contrato y este change lo modifica.
