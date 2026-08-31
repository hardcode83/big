# Proposal: reservation-property-identity

## Why

La maqueta de Stitch del 2026-08-23 destapó dos defectos gemelos en la pantalla de reservas,
ambos porque el contrato `ReservationResponse` no da lo que la columna debe enseñar:

- **Property**: `reservations-view.tsx:159` pinta `{row.propertyId}` y eso es un UUID
  (`981b5c2e-11a4-401b-8459-a97d88b2c14e` en la maqueta) porque `ReservationResponse` tiene
  27 campos y de la propiedad solo expone `property_id`.
- **Guest**: `reservations-view.tsx:156` pinta `{row.guestId ?? "—"}` — un UUID o una raya —,
  aunque `GuestSummary` tiene `fullName`.

El FE no puede arreglar esto: no hay nada mejor en el contrato que copiar. Mismo problema
y misma forma que ya resolvieron `cleaner-task-context` (entregado 2026-08-21) y
`tech-incident-context`: `CleaningTaskResponse` e `IncidentResponse` devolvían
`property_id` como UUID pelado, y la solución en ambos casos fue **resolver el contexto en
el servidor**, sin pedirle al cliente una segunda llamada a `/properties`. Esta entrada es
el tercer caso y debe seguir ese patrón, no inventar otro.

Fuente larga: `sdd/roadmap/reservation-property-identity.md`. Maqueta:
`docs/design/2026-08-23-stitch-export/README.md`.

## What changes

`ReservationResponse` gana cuatro campos derivados en el servidor:

- `property_name` (string legible) y `property_internal_code` (código humano,
  p.ej. `REDES11` / `PAJARITOS8`) — populate desde la `Property` referenciada.
- `guest_full_name` (string del `GuestSummary.fullName`) — populate desde el `Guest`
  referenciado.

Estos campos aparecen tanto en la lista (`GET /api/v1/reservations`, vía
`ReservationPageResponse`) como en el detalle (`GET /api/v1/reservations/{id}`, vía
`ReservationResponse`). La resolución es server-side: el `use_case` que arma la respuesta
hace una segunda lectura acotada al tenant —mismo patrón de composición con `tenant_id`
explícito por consulta que `dashboard-api` D2 ya fija y que `cleaner-task-context` y
`tech-incident-context` replican—, sin JOIN conjunto propio y sin obligar al cliente a
pedir `/properties` o `/guests`. El conjunto de permisos de cada rol no se mueve: quien
tiene `READ_RESERVATIONS` lee los nuevos campos; nadie gana `READ_PROPERTIES` ni
`READ_GUESTS` por esto.

Se distingue de los dos precedentes solo en la **forma** del cambio, no en el principio:
allí la proyección vivía en un endpoint nuevo (`/{id}/context`) porque el rol no podía ver
la entidad; aquí el rol ya tiene `READ_RESERVATIONS` y la respuesta de lista/detalle, así
que el contexto cabe en ese mismo contrato —mismo principio, sin endpoint hermano.

## Requirements

### R1 — Lista de reservas expone identidad legible de la vivienda

**As a** operador que mira `GET /api/v1/reservations`, **I want** que cada fila incluya
`property_name` y `property_internal_code` además del `property_id` actual, **so that**
la columna Property enseñe un nombre o un código humano en vez de un UUID.

Acceptance criteria:

1. WHEN `GET /api/v1/reservations` responde `200`, THE SYSTEM SHALL incluir en cada
   elemento, además del actual `property_id`, los campos `property_name` (string) y
   `property_internal_code` (string).
2. IF el `property_id` de una fila no resuelve dentro del tenant del token, THEN THE
   SYSTEM SHALL devolver `property_name` y `property_internal_code` como `null` con su
   clave, y SHALL NOT degradar el resto de la respuesta — la fila de la reserva sigue
   siendo útil para el resto de columnas.
3. THE SYSTEM SHALL mantener `property_id` en la respuesta: se añade, no se sustituye.
   La maqueta y `frontend/features/reservations/data/dto.ts:76` siguen dependiendo del
   identificador.

### R2 — Detalle de reserva expone la misma identidad legible de la vivienda

**As a** operador que abre `GET /api/v1/reservations/{id}`, **I want** que la respuesta
lleve los mismos `property_name` y `property_internal_code` que la lista, **so that** la
pantalla de detalle no quede en peor situación que la lista (un UUID donde la lista ya
muestra `REDES11`).

Acceptance criteria:

1. WHEN `GET /api/v1/reservations/{id}` responde `200`, THE SYSTEM SHALL devolver los
   mismos `property_name` y `property_internal_code` que R1 fija para la lista.
2. IF el `property_id` no resuelve dentro del tenant del token, THEN THE SYSTEM SHALL
   devolver los dos campos como `null` con su clave, y SHALL NOT responder `404` por
   ese motivo — la reserva sí resuelve, lo que falla es su FK a `properties`. Mismo
   criterio que `cleaner-task-context` aplica a su reserva colgante (la propiedad
   alimenta los campos nuevos, pero la entidad principal sigue siendo la reserva).

### R3 — Lista de reservas expone identidad legible del huésped

**As a** operador que mira `GET /api/v1/reservations`, **I want** que cada fila incluya
`guest_full_name` además del `guest_id` actual, **so that** la columna Guest enseñe un
nombre en vez de un UUID o una raya.

Acceptance criteria:

1. WHEN `GET /api/v1/reservations` responde `200`, THE SYSTEM SHALL incluir en cada
   elemento, además del actual `guest_id`, el campo `guest_full_name` (string).
2. IF `guest_id` es `null` (reserva manual sin huésped), THEN THE SYSTEM SHALL devolver
   `guest_full_name` como `null` con su clave.
3. IF `guest_id` está informado pero no resuelve dentro del tenant del token, THEN THE
   SYSTEM SHALL devolver `guest_full_name` como `null` con su clave, y SHALL NOT degradar
   el resto de la respuesta. Misma forma que R1.2 y R2.2.

### R4 — Detalle de reserva expone la misma identidad legible del huésped

**As a** operador que abre `GET /api/v1/reservations/{id}`, **I want** que la respuesta
lleve el mismo `guest_full_name` que la lista, **so that** la pantalla de detalle no
pierda lo que la lista ya muestra.

Acceptance criteria:

1. WHEN `GET /api/v1/reservations/{id}` responde `200`, THE SYSTEM SHALL devolver el
   mismo `guest_full_name` que R3 fija para la lista.
2. IF `guest_id` es `null` o no resuelve dentro del tenant del token, THEN THE SYSTEM
   SHALL devolver `guest_full_name` como `null` con su clave, y SHALL NOT responder
   `404` por ese motivo.

### R5 — Resolución server-side, sin nuevas peticiones cliente

**As a** mantenedor del backend, **I want** que `property_name`, `property_internal_code`
y `guest_full_name` se pueblen en el servidor desde filas ya leídas en la misma
consulta, **so that** el cliente no necesite pedir `/properties` ni `/guests` para
resolver esas etiquetas, y el conjunto de filas visibles no se amplíe por hacerlo.

Acceptance criteria:

1. THE SYSTEM SHALL poblar los tres campos derivados leyendo la `Property` y el `Guest`
   referenciados, en la **misma transacción** que carga la reserva, y SHALL NOT exigir al
   cliente una segunda petición para resolver esas etiquetas. Mismo principio que
   `cleaner-task-context` y `tech-incident-context`.
2. THE SYSTEM SHALL componer la lectura con un `tenant_id` explícito por consulta
   (regla D2 de `sdd/specs/dashboard-api.md`), en lugar de un `JOIN` conjunto propio:
   un adaptador de proyección sería el segundo sitio donde se escribe el scope de
   tenant, y un `WHERE` adicional dentro de un `JOIN` es la fila que
   `guest-portal-api` tuvo que cerrar a mano. La composición además es **más estricta**
   que un `JOIN`: una `reservation` con `property_id` o `guest_id` apuntando a otro
   tenant resuelve a `null` para los campos derivados y degrada la respuesta
   parcialmente, no a error.
3. THE SYSTEM SHALL demostrar el cruce de tenant con tests propios: una `reservation`
   cuya `property_id` apunta a una `property` de otro tenant debe devolver los campos
   derivados como `null` con su clave, no los valores cruzados, y nunca un error 5xx.
   Igual para `guest_id` apuntando a otro tenant.

   **Asimetría `property_id` / `guest_id` a nivel de esquema**: la FK de `reservations.guest_id`
   es compuesta (`ForeignKeyConstraint(["tenant_id", "guest_id"], ["guests.tenant_id", "guests.id"], name="fk_reservations_guest_within_tenant")`,
   añadida por `guest-portal-api` en Alembic `e7a3c419d82b`), así que el caso
   "guest_id de otro tenant" es **estructuralmente imposible** — la fila no puede existir
   en disco. La cláusula "Igual para `guest_id` apuntando a otro tenant" se satisface
   **vacuamente**: el cruce queda colapsado al caso "no hay fila" por construcción de
   esquema, y la aplicación degenera ese caso a `guest_full_name = null` con su clave
   del mismo modo. El test del cruce por `guest_id` no se puede escribir porque ningún
   INSERT lo producirá sin violar la constraint; `backend/tests/reservations/test_identity_isolation.py`
   documenta la asimetría y deja el lado cubrible (cruce por `property_id`) cubierto.
   El propietario del change [`guest-portal-api`](https://github.com/autohostai-labs/AutoHostAI/blob/main/sdd/roadmap/guest-portal-api.md)
   decidió la asimetría a propósito — la diferencia entre `guest_id` (PII del tenant) y
   `property_id` (recurso del tenant) lo justifica, y la nota al pie de
   `backend/app/reservations/infrastructure/models.py:46-58` la fecha.
4. THE SYSTEM SHALL fijar el conjunto de campos derivados con un test propio, de modo
   que añadir uno (dirección de la propiedad, email del huésped, etc.) sea un acto
   deliberado y no una deriva. Misma forma que
   `sdd/specs/cleaner-task-context.md` §"La proyección nunca lleva" y
   `sdd/specs/tech-incident-context.md` §"Lo que la proyección nunca lleva".

### R6 — Permisos sin ampliación

**As a** dueño del modelo de autorización, **I want** que este cambio no amplíe el
conjunto de permisos de ningún rol, **so that** no se conceda `READ_PROPERTIES` ni
`READ_GUESTS` implícitamente a quien solo mira reservas — argumento decisivo que ya
pesó en `cleaner-task-context` y `tech-incident-context`.

Acceptance criteria:

1. THE SYSTEM SHALL permitir a quien ya tiene `READ_RESERVATIONS` leer los nuevos
   `property_name`, `property_internal_code` y `guest_full_name`, y SHALL NOT añadir
   `READ_PROPERTIES` ni `READ_GUESTS` al conjunto de permisos requerido para esta ruta.
2. THE SYSTEM SHALL mantener el conjunto de permisos de cada rol
   (`PROPERTY_MANAGER`, `TENANT_OWNER`, etc.) inalterado tras este cambio. La matriz de
   `backend/app/auth/domain/policy.py` no se toca.
3. THE SYSTEM SHALL seguir negando esta ruta con `403` al rol `CLEANER` (sin
   `READ_RESERVATIONS`) igual que hoy, y al portador de un token de huésped con `401`.

## Out of scope

- **Render del importe vacío** (`{row.grossAmount ?? ""} {row.currency}` → `" EUR"`). La
  misma maqueta lo destapó, pero es presentación pura y no toca el contrato. Entrada
  `reservation-amount-empty-render` en el roadmap.
- **Una proyección `/reservations/{id}/context` separada**, al modo de
  `cleaner-task-context` y `tech-incident-context`. Descartado de antemano: el rol ya
  tiene `READ_RESERVATIONS` y la respuesta de lista/detalle, así que el contexto cabe
  en ese mismo contrato sin un endpoint hermano. Si en el futuro un rol sin
  `READ_RESERVATIONS` necesita contexto de reserva, esa puerta se abre con su propia
  ruta y su propia decisión de steering, no se fuerza aquí.
- **La UI.** La maqueta vive en `docs/design/2026-08-23-stitch-export/`; pasar de UUID a
  nombre es de FE y de un change posterior.
- **Campos adicionales de `Property` o `Guest`** que no se pidieron explícitamente
  (dirección postal, `access_notes`, email, teléfono, etc.). Por la regla «una
  proyección puede estrechar, nunca unir» (decisión D10 de `sdd/specs/dashboard-api.md`),
  añadir un campo que un permiso guarda como un todo es una decisión de steering, no
  una derivación de este change.
- **Cifrado en reposo de columnas de texto libre** (`access_notes`, etc.). Es
  `plaintext-sink-encryption-at-rest` en el roadmap, sin relación con este change.
- **Backwards compatibility del frontend.** El contrato cambia y
  `frontend/features/reservations/data/dto.ts:76` (`propertyId: string`) se regenera
  desde `backend/openapi.json`. El FE consume el artefacto regenerado y la columna
  pasa de UUID a nombre sin rama de compat — son 2 viviendas en el MVP y el FE aún no
  pinta este campo en producción.

## Affected specs

- `sdd/specs/reservations.md` — modificar. R1–R4 extienden el contrato de respuesta de
  `GET /api/v1/reservations` y `GET /api/v1/reservations/{id}`; R5 y R6 se añaden a la
  sección de consultas por petición (D2) y a la de autorización.
- `sdd/specs/api-contract.md` — modificar. La regeneración y el commit del artefacto
  derivado del frontend (`frontend/lib/api/generated/openapi.d.ts`) son parte del
  contrato publicado (mismo puente que `cleaner-task-context` y `tech-incident-context`
  citan).
- `sdd/specs/auth-tenancy.md` — sin cambios estructurales. La matriz de permisos no se
  mueve (R6); solo se referencia la decisión D10 para futuros añadidos.

## Verificación cruzada

- `sdd/roadmap/reservation-property-identity.md` — fuente del problema, con el patrón de
  los dos precedentes ya medidos.
- `sdd/roadmap/cleaner-task-context.md` y `sdd/roadmap/tech-incident-context.md` — los
  dos cambios entregados que aplican el mismo patrón (con un endpoint `/context`
  separado; este change diverge en la forma, no en el principio).
- `sdd/specs/cleaner-task-context.md` §"La proyección: a qué propiedad va la limpiadora"
  y `sdd/specs/tech-incident-context.md` §"La proyección: a qué propiedad va el
  técnico" — los SHALL de campos derivados, `null` con clave y composición por
  `tenant_id` que R1–R5 reflejan.
- `sdd/steering/security.md` regla 11 — el censo de sumideros y la decisión D10
  («agregar no puede conceder») que R6 aplica.
- `docs/design/2026-08-23-stitch-export/README.md` — maqueta de Stitch que destapó los
  dos defectos (Property y Guest) en la misma fila de problema.