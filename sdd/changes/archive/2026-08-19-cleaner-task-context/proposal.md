# Proposal: cleaner-task-context

## Why

PRD §11 «UI de limpiadora (mobile-first)» enumera nueve cosas que la limpiadora ve, y tres de
ellas —**dirección**, **info de checkout previo** y **deadline del próximo check-in**— viven hoy
detrás de permisos que el rol `CLEANER` no tiene. Su política es exactamente cinco permisos
(`backend/app/auth/domain/policy.py:327`): `READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
`READ_OWN_NOTIFICATIONS`, `READ_CLEANING_TASKS`, `EXECUTE_CLEANING_TASKS`. Sin `READ_PROPERTIES`
ni `READ_RESERVATIONS`, las rutas de propiedades, dashboard, timeline y reservas le contestan
`403`, y `CleaningTaskResponse` (`backend/app/cleaning/api/schemas.py:151`) le devuelve
`property_id` y `reservation_id` como UUID pelados.

El efecto práctico: la app de la limpiadora no puede decirle **a qué piso tiene que ir**. Eso
choca de frente con el principio 3 de `sdd/steering/product.md` —«MVP de calidad producción
end-to-end […] nunca maqueta visual»— y es lo que hizo que `cleaner-app`, que nació como entrada
`[FE]`, no fuera implementable. Al abrir su `/sdd:new` el 2026-08-18 se separó esta entrada y
`cleaner-incident-report`, y `cleaner-app` pasó a declararlas en su `needs`.

La vía barata —dar `READ_PROPERTIES` y `READ_RESERVATIONS` al rol `CLEANER`— está descartada: le
abriría el CRUD entero de propiedades y las reservas con sus importes, su huésped y sus
`internal_notes`, para resolver un nombre y una dirección. Este change entrega en su lugar una
**proyección de solo lectura acotada a la tarea propia del llamante**.

## What changes

Después de este change existe una lectura que, dado un `cleaning_task_id` **asignado al llamante**,
devuelve el contexto operativo que PRD §11 exige: identificación legible de la propiedad, su
dirección postal, la hora de checkout de la reserva saliente y el deadline del próximo check-in.
El acotamiento por fila es el mismo mecanismo que ya usa el módulo de limpieza —
`CleaningActor.restrict_to_cleaner_id` (`backend/app/cleaning/application/use_cases.py:495-511`),
que deriva el id del **token** y nunca de un campo de la petición—, de modo que la respuesta no
amplía el conjunto de tareas que una limpiadora puede ver: exactamente las suyas, y `404` para
todo lo demás, igual que hoy. La proyección es **una lista cerrada de campos**, no un volcado de
`Property` ni de `Reservation`, y no concede ninguno de los dos permisos de lectura existentes:
`PROPERTY_MANAGER` y `TENANT_OWNER` siguen leyendo lo que leían por sus rutas de siempre.

## Requirements

### R1 — La limpiadora ve a qué propiedad va

**As a** limpiadora, **I want** ver el nombre y la dirección de la propiedad de mi tarea,
**so that** pueda ir al piso correcto sin preguntarle al manager.

Acceptance criteria:

1. WHEN un usuario con rol `CLEANER` pide el contexto de una tarea de limpieza que tiene asignada,
   THE SYSTEM SHALL devolver `200` con el `name` y el `internal_code` de la propiedad y sus campos
   de dirección postal (`address_line1`, `address_line2`, `city`, `province`, `postal_code`,
   `country`).
2. WHEN esa misma respuesta se construye, THE SYSTEM SHALL incluir el `timezone` de la propiedad,
   porque todos los instantes de R2 se interpretan en él.
3. IF un campo de dirección es `NULL` en la propiedad, THEN THE SYSTEM SHALL devolverlo como
   `null` y no omitir la clave.
4. WHEN la respuesta se serializa, THE SYSTEM NEVER SHALL incluir `access_notes`, `cleaning_notes`,
   `emergency_notes`, `wifi_password_encrypted` ni `has_wifi_password`.

### R2 — La limpiadora ve su ventana de trabajo

**As a** limpiadora, **I want** saber a qué hora sale el huésped anterior y para cuándo tiene que
estar listo el piso, **so that** pueda ordenar mi jornada y no llegar antes de que se vacíe.

Acceptance criteria:

1. WHEN existe una reserva saliente asociada a la tarea, THE SYSTEM SHALL devolver su hora de
   checkout, resolviendo `Reservation.check_out_time` y cayendo a
   `Property.default_check_out_time` cuando la reserva no la trae.
2. WHEN existe una reserva entrante posterior en la misma propiedad, THE SYSTEM SHALL devolver el
   deadline del próximo check-in, resuelto igual contra `Property.default_check_in_time`.
3. IF no hay reserva entrante posterior, THEN THE SYSTEM SHALL devolver el deadline como `null`,
   y no como una fecha inventada ni un error.
4. WHEN se devuelve cualquiera de los dos instantes, THE SYSTEM SHALL emitirlo en ISO 8601 con
   offset explícito.
5. WHEN la respuesta se serializa, THE SYSTEM NEVER SHALL incluir el importe bruto, la comisión de
   la OTA, el importe neto, el estado de pago, el canal, el `guest_id`, `special_requests` ni
   `internal_notes` de ninguna reserva.

### R3 — El acotamiento por fila no se amplía

**As a** responsable de seguridad, **I want** que esta lectura no ensanche lo que una limpiadora
alcanza, **so that** una ruta nueva no se convierta en el bypass del aislamiento del módulo.

Acceptance criteria:

1. WHEN el llamante tiene rol `CLEANER`, THE SYSTEM SHALL restringir la consulta a las tareas cuyo
   `assigned_cleaner_id` sea el id del propio llamante, derivado del token.
2. IF un usuario con rol `CLEANER` pide el contexto de una tarea asignada a otra limpiadora,
   THEN THE SYSTEM SHALL responder `404`, con el mismo cuerpo que una tarea inexistente.
3. IF la tarea pertenece a otro tenant, THEN THE SYSTEM SHALL responder `404`.
4. WHEN el llamante no tiene el permiso de lectura de tareas de limpieza, THE SYSTEM SHALL
   responder `403` antes de tocar la base de datos.
5. WHEN el llamante tiene rol `PROPERTY_MANAGER` o `TENANT_OWNER`, THE SYSTEM SHALL devolver el
   contexto de cualquier tarea de su tenant, sin el acotamiento de la cláusula 1.

### R4 — El contrato queda publicado y consumible

**As a** desarrolladora del frontend, **I want** que la proyección esté en el contrato OpenAPI con
tipos exactos, **so that** `cleaner-app` la consuma con los tipos generados y sin envoltorios
propios.

Acceptance criteria:

1. WHEN se regenera `backend/openapi.json`, THE SYSTEM SHALL declarar la operación con su esquema
   de respuesta enumerado campo a campo.
2. WHEN la operación falla por tarea no encontrada o no accesible, THE SYSTEM SHALL responder con
   el sobre de error de PRD §23 y el código `NOT_FOUND`.
3. WHEN la operación se declara, THE SYSTEM SHALL documentar en su descripción que el conjunto de
   tareas visibles depende del rol del token y no es ensanchable por parámetro.

## Out of scope

- **Reportar una incidencia desde la tarea** (PRD §11 y §12). No existe `POST /api/v1/incidents`,
  `Incident` no tiene `cleaning_task_id` y `IncidentSource.CLEANER` no tiene escritor de
  producción. Es la entrada `cleaner-incident-report`, hermana de esta.
- **Toda la UI**: `/cleaner` y `/cleaner/tasks/[id]` siguen siendo `RoutePlaceholder`. Es
  `cleaner-app`, que declara esta entrada en su `needs`.
- **Multipart en `ApiClient`**: `frontend/lib/api/client.ts` solo serializa JSON, así que la
  subida de fotos no es llamable desde el frontend todavía. Es de `cleaner-app`.
- **Dar `READ_PROPERTIES` o `READ_RESERVATIONS` al rol `CLEANER`**: descartado en *Why*; este
  change no toca la tabla de permisos de `policy.py` salvo para lo que decida su design.
- **Exponer códigos de acceso o `access_records.notes`**: `CLEANER` no tiene
  `READ_ACCESS_RECORDS` y PRD §11 no pide accesos en esta pantalla, así que la decisión de
  steering aparcada en `sdd/roadmap/cleaner-app.md` **no se dispara aquí**. Si el design la
  necesitara, es una entrada de la regla 11 y se aprueba allí, no de paso.
- **Filtrar tareas por fecha**: `CleaningTaskFilters` (`backend/app/cleaning/domain/repositories.py:41`)
  no tiene rango de fechas y el orden es `created_at DESC`. Es una carencia real de la lista, pero
  es del módulo de limpieza y no de esta proyección.

## Affected specs

- `sdd/specs/cleaning.md` — la proyección cuelga de una tarea de limpieza y reusa su acotamiento
  por rol.
- `sdd/specs/auth-tenancy.md` — si el design introduce un permiso nuevo en lugar de reusar
  `READ_CLEANING_TASKS`, la tabla de política del rol `CLEANER` cambia.
- `sdd/specs/properties-crud.md` — queda una segunda vía de lectura de campos de `Property`,
  con su propia lista cerrada.
- `sdd/specs/reservations.md` — ídem para las horas de check-in/check-out.
- `sdd/specs/cleaner-task-context.md` *(no existe aún — se creará al archivar)*.

## ASSUMPTION

- **La «reserva saliente» es la que la tarea ya referencia.** `CleaningTask.reservation_id` es
  nullable, así que R2.1 asume que cuando está informado es la reserva cuyo checkout dispara la
  limpieza. Si el design encuentra que no siempre lo es, la resolución pasa a ser por propiedad y
  fecha, y R2 se ajusta.
- **Una sola tarea por petición.** R1-R4 describen el contexto de *una* tarea. Si `/cleaner`
  necesita la dirección de las N tareas del listado sin N peticiones, eso es una decisión de forma
  del design (proyección embebida en el listado vs. recurso aparte), no un requisito distinto.
