# Contexto operativo de una tarea de limpieza

## Purpose

Dice a la limpiadora **a qué piso tiene que ir y con qué margen**, sin concederle ninguno de los
permisos que guardan las propiedades y las reservas. Es la lectura que PRD §11 exige de la app de
limpiadora —identificación de la propiedad, su dirección postal, la hora de salida del huésped
anterior y el plazo del siguiente check-in— entregada como una **proyección de solo lectura
acotada a la tarea propia del llamante**.

Existe porque el rol `CLEANER` tiene exactamente cinco permisos y ni `READ_PROPERTIES` ni
`READ_RESERVATIONS` están entre ellos (`backend/app/auth/domain/policy.py`): las rutas de
propiedades, dashboard, timeline y reservas le contestan `403`, y `CleaningTaskResponse` le da
`property_id` y `reservation_id` como UUID pelados. La alternativa barata —concederle esos dos
permisos— quedó descartada: abriría el CRUD entero de propiedades y las reservas con sus importes,
su huésped y sus `internal_notes` para resolver un nombre y una dirección.

Cuelga de una tarea de [`cleaning`](cleaning.md) y reusa su acotamiento por rol sin ampliarlo. El
*cómo se opera* está en [`docs/cleaning.md`](../../docs/cleaning.md).

## Requirements

### La proyección: a qué propiedad va la limpiadora

- WHEN se solicita `GET /api/v1/cleaning-tasks/{task_id}/context` sobre una tarea alcanzable por
  el llamante, THE SYSTEM SHALL devolver `200` con el `property_name` y el
  `property_internal_code` de la propiedad y sus campos de dirección postal (`address_line1`,
  `address_line2`, `city`, `province`, `postal_code`, `country`).
- THE SYSTEM SHALL incluir el `timezone` de la propiedad, porque es lo que permite leer como un
  lugar el offset de los dos instantes de la sección siguiente.
- IF un campo de dirección es `NULL` en la propiedad, THEN THE SYSTEM SHALL devolverlo como `null`
  **con su clave**, y no omitirla. No hay `exclude_none` ni `response_model_exclude_none` en
  ninguna parte de `backend/app`, así que es comportamiento heredado de pydantic: lleva su propio
  test contra el cuerpo serializado en vez de darse por hecho.
- THE SYSTEM SHALL devolver **once campos y solo once**: los nueve de la propiedad más
  `checkout_at` y `next_checkin_deadline`.

### La ventana de trabajo

- WHEN la tarea referencia una reserva que resuelve dentro del tenant, THE SYSTEM SHALL devolver
  en `checkout_at` el final de la estancia resuelto por `effective_bounds`, que es
  `Reservation.check_out_time` con fallback a `Property.default_check_out_time`.
- THE SYSTEM SHALL devolver en `next_checkin_deadline` la llegada `CONFIRMED` más próxima igual o
  posterior al ancla, resuelta con el mismo fallback contra `Property.default_check_in_time`.
- THE SYSTEM SHALL emitir los dos instantes en ISO 8601 con offset explícito, en el timezone de la
  propiedad. Sale de que `effective_bounds` devuelve instantes con zona y de la serialización por
  defecto de pydantic; no hay formateador propio.
- IF no hay ninguna llegada `CONFIRMED` en los **14 días** siguientes al ancla, THEN THE SYSTEM
  SHALL devolver `next_checkin_deadline` como `null`, y no como una fecha inventada ni un error.
  Ese `null` significa por tanto «no hay llegada `CONFIRMED` dentro del horizonte», **no** «no hay
  llegada»; la `description` de la operación lo dice con esas palabras.
- THE SYSTEM SHALL aplicar el horizonte **también sobre el valor**, no solo sobre la ventana de la
  consulta: `list_for_properties` toma `date`s, así que la ventana admitiría una llegada más
  tardía ese mismo día que el instante del horizonte, hasta un día más allá de la cota.
- WHILE la llegada siguiente está en estado `PENDING`, THE SYSTEM SHALL no imponer deadline y
  devolver `null`. El filtro `CONFIRMED` se hereda de `process_checkouts` en lugar de divergir de
  él: dos políticas de elegibilidad en el mismo repositorio serían peor que una discutible.
- THE SYSTEM SHALL medir el ancla desde el checkout resuelto, y **no** desde el instante de la
  petición, cuando ese checkout existe: la ventana de una limpieza es `[checkout, llegada
  siguiente]` y ninguno de sus dos extremos es función de cuándo se preguntó.
- IF la tarea no referencia ninguna reserva, THEN THE SYSTEM SHALL devolver `checkout_at` como
  `null` y anclar el deadline en el instante de la petición. Es la tarea manual creada por
  `POST /cleaning-tasks`: no hay huésped saliente, así que `null` es la respuesta honesta.
- IF `reservation_id` está informado pero **no resuelve dentro del tenant** —fila borrada, o
  puntero a otro tenant—, THEN THE SYSTEM SHALL degradar igual (`checkout_at` a `null`, ancla en
  el instante de la petición) y registrar un `logger.warning` con `tenant_id`, `task_id` y
  `reservation_id`. No es un `404`, a diferencia del puntero de propiedad, porque la propiedad
  alimenta nueve de los once campos y la reserva solo `checkout_at`: negar el contexto entero le
  quitaría a la limpiadora la dirección, que es la mitad de lo que esta ruta existe para dar.
  Una reserva de otro tenant y una inexistente producen el mismo `None`, así que esa rama no es un
  oráculo de existencia y no se lee ningún campo de la reserva no resuelta.
- IF `effective_bounds` no puede materializar la estancia, THEN THE SYSTEM SHALL devolver
  `checkout_at` como `null` y anclar en el instante de la petición. Aquí **no** se degrada a
  `now` como hace `_effective_checkout`: aquello es una pista de planificación, y esto es una hora
  que se muestra a una persona.
- THE SYSTEM SHALL resolver los dos instantes **en la lectura**, y no devolver
  `scheduled_start`/`scheduled_end` de la tarea. Los dos pares pueden discrepar legítimamente y
  significan cosas distintas: `scheduled_*` es el **plan** que el planificador se comprometió a y
  sobre el que se construyeron la asignación y el SLA, y `checkout_at`/`next_checkin_deadline` es
  la respuesta **de ahora**. Se llaman distinto para que la discrepancia no se lea como una
  contradicción, y la `description` de la operación lo explica.
- THE SYSTEM SHALL no repetir `scheduled_*` en esta respuesta: el cliente ya tiene la tarea, que
  es de donde viene a esta ruta.
- THE SYSTEM SHALL derivar el instante de la petición del reloj del servidor y nunca de un campo
  de la petición: ancla el deadline cuando la tarea no tiene reserva saliente, así que un llamante
  que pudiera fijarlo desplazaría lo que la respuesta reporta.

### Lo que la proyección nunca lleva

- THE SYSTEM SHALL construir la respuesta desde un dataclass congelado del dominio
  (`CleaningTaskContext`) espejado campo a campo en el contrato, y SHALL NOT serializar nunca una
  entidad `Property` ni `Reservation`. Es lo que convierte las dos exclusiones de abajo en
  **estructurales**: un campo que no está en el dataclass no tiene dónde aterrizar.
- THE SYSTEM SHALL NOT incluir `access_notes`, `cleaning_notes`, `emergency_notes`,
  `wifi_password_encrypted` ni `has_wifi_password`. Las tres primeras son sumideros de texto plano
  de la regla 11 de `steering/security.md`, auditables pero no denylisted, así que un `Property`
  volcado por `from_attributes` los llevaría.
- THE SYSTEM SHALL NOT incluir el importe bruto, la comisión de la OTA, el importe neto, el estado
  de pago, el canal, el `guest_id`, `special_requests` ni `internal_notes` de ninguna reserva.
- THE SYSTEM SHALL fijar el conjunto de campos con un test propio, de modo que añadir uno sea un
  acto deliberado y no una deriva.
- **La regla para quien añada un campo: una proyección puede estrechar, nunca unir.** Un campo que
  un permiso guarda *como un todo* —un importe de reserva, el nombre de un huésped— no entra aquí:
  pasa por la decisión D10 de [`dashboard-api`](dashboard-api.md). Esta capacidad **diverge** de
  esa regla («agregar no puede conceder») a propósito y con alcance acotado: su sujeto es un
  agregado sobre una raíz que el llamante ya puede leer entera, y esto no es una unión de permisos
  sino nueve campos y dos instantes derivados, sobre un conjunto de filas **más estrecho** que el
  que `READ_PROPERTIES` daría.

### Acotamiento por fila y autorización

- THE SYSTEM SHALL exigir `READ_CLEANING_TASKS` en la puerta, y responder `403` antes de tocar la
  base de datos cuando el llamante no lo tiene. No hay permiso nuevo: uno propio lo tendrían
  exactamente los roles que ya tienen éste y acotaría exactamente las filas que ya están acotadas.
- WHILE el llamante tiene rol `CLEANER`, THE SYSTEM SHALL restringir la consulta a las tareas cuya
  `assigned_cleaner_id` sea la suya, derivada del rol **persistido** que se relee de la fila del
  usuario en cada petición, y no de ningún campo de la petición.
- WHILE el llamante tiene rol `PROPERTY_MANAGER` o `TENANT_OWNER`, THE SYSTEM SHALL devolver el
  contexto de cualquier tarea de su tenant, sin ese acotamiento.
- IF la tarea no existe, pertenece a otro tenant, está asignada a otra limpiadora, o su
  `property_id` no resuelve dentro del tenant, THEN THE SYSTEM SHALL responder `404 NOT_FOUND` con
  un cuerpo **idéntico** en los cuatro casos. Sale de `CleaningTaskNotFoundError`, ya en la tabla
  de `cleaning/api/errors.py`: no hace falta excepción nueva ni fila nueva.
- THE SYSTEM SHALL llevar un `tenant_id` explícito en cada una de las lecturas que compone, en
  lugar de un `SELECT` conjunto propio. Es la regla D2 de [`dashboard-api`](dashboard-api.md) —un
  adaptador de proyección sería el segundo sitio donde se escribe el scope de tenant— y aquí la
  composición además es **más estricta** que un `JOIN`: una tarea que apunte a la propiedad de
  otro tenant resuelve a `None` y se convierte en `404`, que es la fila que el panel de seguridad
  de [`guest-portal-api`](guest-portal-api.md) tuvo que cerrar a mano con un segundo `WHERE`
  dentro de su join.
- THE SYSTEM SHALL demostrar con tests propios el cruce de tenant, incluida la tarea que apunta a
  la propiedad de otro tenant: D2 lo cierra por composición, pero eso se demuestra, no se afirma.

### Contrato publicado

- THE SYSTEM SHALL declarar la operación en `backend/openapi.json` con su esquema de respuesta
  enumerado campo a campo, y SHALL mantener regenerado y commiteado el artefacto derivado del
  frontend `frontend/lib/api/generated/openapi.d.ts` — las dos mitades del mismo puente.
- THE SYSTEM SHALL declarar su `404` en la propia ruta con el sobre de error de PRD §23 y el
  código `NOT_FOUND`, con un `responses=` per-endpoint.
- THE SYSTEM SHALL documentar en la `description` de la operación que el conjunto de tareas
  visibles depende del rol persistido del token y **no es ensanchable por parámetro**, qué
  significa cada `null`, y que los dos instantes no son `scheduled_start`/`scheduled_end`.

## Consultas por petición

Hasta **cuatro** sentencias sobre una sola tarea: `tasks.get`, `properties.get`,
`reservations.get` y `reservations.list_for_properties`. Son **tres** cuando la tarea no tiene
reserva, porque entonces no hay `reservations.get` que hacer, y menos aún en los caminos que
terminan en `404`. Es el coste de la composición de D2, y se paga en la lectura de una tarea, no
en un listado.

## Fuera de alcance

- **La UI.** `/cleaner` y `/cleaner/tasks/[id]` los implementa `cleaner-app`, que declara esta
  entrada en su `needs`.
- **El contexto embebido en el listado.** `CleaningTaskPageResponse` no lo lleva: lo decidirá
  `cleaner-app` con una pantalla real delante, y con 2 viviendas en el MVP N es 1-3.
- **Códigos de acceso y `access_records.notes`.** `CLEANER` no tiene `READ_ACCESS_RECORDS` y
  PRD §11 no pide accesos en esta pantalla. La decisión de steering que
  `sdd/roadmap/cleaner-app.md` tenía aparcada sobre las cuatro columnas auditables-no-denylisted **no
  se disparó aquí**, y éste es el por qué no: lo que la dispara es que el conjunto de lectores de una
  de esas columnas crezca a un rol que hoy no la tiene, y esta proyección no lee ninguna de las
  cuatro. **La disparó [`tech-incident-context`](tech-incident-context.md) el 2026-08-21**, que sí
  lee `access_notes`: le dio la excepción 6 del censo de la regla 11 y sacó las tres notas de
  `properties` del listado paginado. Lo que sigue pendiente de aquella decisión es el cifrado en
  reposo de las cuatro columnas —entrada `plaintext-sink-encryption-at-rest`— y `access_records.notes`,
  que sigue siendo de `cleaner-app`.
- **Instrucciones de limpieza.** PRD §11 enumera nueve cosas y no pide `cleaning_notes`. Excluirlo
  no es quedarse corto.
- **Los requisitos de foto de la tarea.** El `SHALL` de *once campos y solo once* es lo que los
  mandó a una ruta hermana en vez de aquí: meterlos habría exigido **enmendarlo**, no ampliarlo.
  Viven en [`cleaner-photo-requirements`](cleaner-photo-requirements.md), sobre
  `GET /cleaning-tasks/{task_id}/photo-requirements`, con este mismo permiso y este mismo
  acotamiento por fila. Esta ruta no se tocó al añadirlos.

## Key files

- `backend/app/cleaning/domain/read_models.py` — `CleaningTaskContext`, el dataclass congelado de
  once campos, y el docstring que enumera por qué la lista está cerrada.
- `backend/app/cleaning/domain/windows.py` — `resolve_checkout`, `next_arrival_after` (la regla que
  vivía en `_next_checkin`, con id de exclusión opcional) y `next_arrival_within_horizon`, que es
  donde vive el horizonte de `NEXT_ARRIVAL_HORIZON` = 14 días. Ninguna reimplementa la aritmética
  DST: las tres delegan en `properties/domain/clock_triggers.effective_bounds`.
- `backend/app/cleaning/application/use_cases.py` — `GetCleaningTaskContextUseCase` y su
  `_checkout_and_anchor`; `process_checkouts` es el segundo llamante de `windows.py`.
- `backend/app/cleaning/api/schemas.py` — `CleaningTaskContextResponse`, espejo con
  `from_attributes=True`.
- `backend/app/cleaning/api/tasks_router.py` — `GET /{task_id}/context`, `_CONTEXT_RESPONSES` y la
  `description` del contrato.
- `backend/app/cleaning/api/dependencies.py` — `get_cleaning_task_context_use_case`, con los tres
  repositorios ya usados en el módulo.
- `backend/app/properties/domain/clock_triggers.py` — `effective_bounds`, el único sitio con el
  fallback a los valores por defecto de la propiedad y su política DST.
- `backend/tests/cleaning/test_task_context_{read_model,use_case,api}.py` y
  `backend/tests/cleaning/test_windows.py` — el conjunto de campos fijado, la resolución de los
  dos instantes, el cruce de tenant y el cuerpo serializado.
- `docs/cleaning.md` — cómo se opera.
