# Tasks: seed-data-demo-extension

Orden pensado para que el sistema siga en pie tras cada sección. Las secciones 1-4 no tocan el
comportamiento del comando: barren los tres apuntes heredados, añaden un caso de uso que todavía
nadie invoca, escriben la línea de steering que la sección 8 necesita y meten constantes y una
precondición nueva. De la 5 a la 8 cada sección añade un tramo de la **fase de avance** en el orden
cronológico de D2, dejando el comando funcionando con un dataset más completo. La 9 cierra el
contrato de consola, la idempotencia global, el rollback y el aislamiento. La 10 documenta.

**El orden de ejecución dentro de `apply_plan` es el de la tabla de D2 (`design.md:56-70`) y es
contrato**, no estética: la permutación que siembra las incidencias antes que las estancias pierde
cinco transiciones en silencio. Las secciones 5-8 lo construyen en ese mismo orden, y la 9.1 lo
pinea entero.

Los valores del dataset salen de PRD §27 (`docs/AutoHostAI_PRD_v5_Claude.md:2167-2288`, incidencias
en `:2257-2284`); las decisiones que citan las tareas están en `design.md`.

## 1. Los tres barridos que la entrada arrastra (D13) <!-- panel: PASS 2026-08-16 -->

- [x] 1.1 Subir la validación de la zona horaria del tenant a la fase de precondiciones. Hoy
  `ZoneInfo(tenant.timezone)` se evalúa dentro de `apply_plan`
  (`backend/app/cli/seed_demo.py:413`) y una zona irresoluble sale por el catch-all de `main()`
  (`:887-906`) con la clase de la excepción y «details withheld». Como `build_plan()` no lee la
  base de datos —resuelve el tenant `apply_plan`—, la comprobación va **inmediatamente después de
  resolver el `TenantModel` y antes de `bind_session_to_tenant`** (es decir, antes de la primera
  escritura, que es lo que D11 de `seed-data-demo` exige para que «sin escribir nada» sea una
  propiedad y no una esperanza), levantando `SeedConfigurationError` con la columna
  (`tenants.timezone`) y el valor rechazado. Test en `backend/tests/cli/test_seed_demo.py`: un
  tenant con `timezone` basura aborta con el mensaje que nombra columna y valor, sale con **1** y
  no escribe ninguna fila. [R6.1]

- [x] 1.2 Corregir el docstring de `ReservationIngestor`
  (`backend/app/integrations/application/ingest.py:1-9`): las dos frases que hoy dicen «two»
  pasan a enumerar las **tres** rutas de ingesta — el sync del PMS, el import CSV y el seed de
  demo. Sin cambio de comportamiento y sin test propio. [R6.2]

- [x] 1.3 Cubrir con un test la rama de `SeedIngestError` **sin motivos**
  (`backend/app/cli/seed_demo.py:736-740`), la única del comando que hoy no ejercita ningún test.
  Va en `backend/tests/cli/test_seed_demo.py` junto a
  `test_an_ingest_failure_reaches_the_console_with_its_reasons` (`:205-231`), con `ingest`
  monkeypatcheado devolviendo un informe de `skipped=1, errors=()`: el comando falla en voz alta,
  sale con **2** y su salida dice que hubo filas saltadas aunque no haya motivo que citar. (La
  tabla «Changes by area» de `design.md:304` lo situó en `backend/tests/integrations/`; la
  referencia de línea de D13 apunta a `test_seed_demo.py`, que es donde vive la rama y donde va.)
  [R6.3]

## 2. `ReportIncidentUseCase`: el alta genérica que `maintenance` no tiene (D5) <!-- panel: PASS 2026-08-16 -->

- [x] 2.1 Añadir `ReportIncidentUseCase` a
  `backend/app/maintenance/application/use_cases.py`, sobre `_IncidentFlowBase` (`:525-549`) y
  calcado de `ReportGuestIncidentUseCase` pero sin sus dos suposiciones: no fija
  `source=IncidentSource.GUEST` (`:153`) y no exige `reservation_id` ni `reporter_token_hash`
  (`:137-148`). Firma de `design.md` §«Data & interfaces», **enmendada el 2026-08-16 en el gate
  del panel de esta sección**: `tenant_id`, `property_id`, `source`, `title`, `description`,
  `actor: IncidentActor` y `now` — sin `reservation_id` ni `reported_by_user_id`, y con un
  `PropertyRepository` más en el constructor que resuelve `property_id` dentro del tenant. El
  porqué (la precondición que `IncidentRepository.add` declara y que el creador existente sólo
  cumple estructuralmente) está en D5. Escribe la entidad, su `AuditLog` (por `_AuditWriter`, que exige actor para
  todo lo que no sea `INCIDENT_CLASSIFIED`, `:281`) y su `TimelineEvent` en la misma transacción,
  componiendo sobre el `uow` inyectado. Hace falta porque el creador existente **no puede** crear
  las tres incidencias de §27: la 3 es `source: CLEANER` y ninguna cuelga de una reserva. Se
  diseña genérico porque `messaging-ai` necesitará exactamente esta alta — lo dice
  `backend/app/maintenance/api/incidents_router.py:11-15`. **No** se añade ninguna ruta HTTP.
  [R1.1, R1.6, D5]

- [x] 2.2 Tests del caso de uso nuevo en `backend/tests/maintenance/` (fichero propio, al modo de
  `test_report_guest_incident.py`): crea la incidencia con el `source` que se le pasa y no con
  `GUEST`; funciona **sin** `reservation_id`; deja la incidencia en `OPEN` con `category`,
  `severity` y `ai_classification` sin escribir; escribe una fila de `AuditLog` con su actor y un
  `TimelineEvent`; rechaza el alta sin actor; y el aislamiento de tenant sobre las tres tablas
  (`steering/security.md` regla 1, `steering/testing.md` DoD §28.18). Verificar además que
  `backend/tests/maintenance/test_free_text_sink_contract.py:192-212` **sigue en verde sin tocar
  su allowlist**: el módulo ya está en ella (`maintenance/application/use_cases.py`), así que un
  escritor más dentro del mismo fichero no mueve el censo. [R1.1, R1.6, D5]

## 3. La cuarta excepción de la regla 9 nombra al seed (D7 / OQ1)

- [x] 3.1 Ampliar la **cuarta excepción de la regla 9** en `sdd/steering/security.md:65-71` para
  que nombre al comando de seed junto al job `classify_incidents`. Es tarea de código de este
  change y no un trámite del design: la propia excepción dice que lo que la amplía es la línea en
  el steering y no la aprobación en un design (`:65`, y el párrafo de `:63`). La entrada debe
  decir tres cosas: **(a)** que se pide por la propiedad que la excepción ya declara como
  fundamento —«no existe el actor»: es un comando de línea de órdenes, no hay persona detrás de
  la clasificación y `actor_ip` no tiene petición de la que salir—, con el precedente exacto de la
  **segunda** excepción de esta misma regla, que aceptó ese argumento para un CLI (`:55`);
  **(b)** que se pide **por esa puerta y no por parecido con el job**; **(c)** su párrafo «lo que
  NO concede», actualizando la frase de `:71` que hoy dice «sólo cuando la ejecuta el job» — sigue
  cubriendo sólo `INCIDENT_CLASSIFIED`, la clasificación manual por
  `POST /incidents/{id}/classify` sigue llevando su actor, y no dice nada sobre las otras once
  acciones del flujo ni sobre ningún otro comando. **Esta tarea va antes que la 8.2**, que es la
  que ejercita la exención. [R1.2, D7]

## 4. Constantes de §27 y el fail-fast de `S3` (D6, D10) <!-- panel: PASS 2026-08-16 -->

- [x] 4.1 Añadir a `backend/app/cli/seed_demo.py`, junto a `_CHECKLIST_ITEMS` (`:173`) y
  `SEED_PROPERTIES` (`:116`), las constantes de las tres incidencias de §27: los seis literales
  (`title` y `description`) más su `property_id` lógico (`REDES11`, `REDES11`, `PAJARITOS8`), su
  `source` (`GUEST`, `GUEST`, `CLEANER`) y la pareja `(category, severity)` que §27 declara y que
  R1.3 usará para contrastar el veredicto del clasificador (`WIFI/LOW`, `ACCESS/HIGH`,
  `APPLIANCE/MEDIUM`). **Constantes del módulo y no texto compuesto**, y ese es todo el punto de
  D6: `incidents.title`/`description` son sumideros de la regla 11 y su excepción 2 concede la
  prosa de quien reporta, no la de un escritor nuestro (`steering/security.md:146-155`). El seed
  es un escritor nuestro; escribiendo constantes versionadas no necesita la excepción, igual que
  `auth-account-recovery` con `notification_logs`. [R1.1, D6]

- [x] 4.2 Añadir en el mismo módulo las seis constantes `bytes` de las fotos —una imagen JPEG
  mínima válida que `detect_image_type` (`backend/app/integrations/domain/storage.py:135`)
  acepte— y una implementación trivial del `Protocol` `ChunkedUpload`
  (`backend/app/cleaning/application/use_cases.py:1267`), que sólo pide `read(size)`. Test: las
  seis pasan `detect_image_type` y el `ChunkedUpload` entrega los bytes completos en trozos.
  [R3.2]

- [x] 4.3 Añadir a las precondiciones el fail-fast de almacenamiento: si el `storage_type` del
  tenant es `S3` y falta `s3_bucket`, `s3_region` o la credencial que resuelve la cadena de boto3,
  abortar con **exit 1** y una frase accionable **antes de abrir la transacción**. (**`s3_endpoint_url`
  se cayó de la lista el 2026-08-16**, DESIGN-CONFLICT del panel resuelto por Jose: un endpoint
  vacío es la configuración correcta para AWS. Y la pregunta por las credenciales la responde
  `credentials_are_resolvable()` del paquete de almacenamiento, no un `import boto3` en el CLI.) Sube aquí porque `storage_for(S3)` levanta `StorageWriteError` y **nunca** cae a
  `LOCAL` (`backend/app/integrations/infrastructure/storage/__init__.py:74-82`): sin esta
  comprobación un `dev` a medio configurar rompería a mitad de la siembra y saldría por el
  catch-all con exit 2 y «details withheld» — el mismo defecto que la 1.1 arregla para la zona
  horaria. Misma ubicación que la 1.1 (tras resolver el tenant, antes de escribir), y ninguna
  variable de entorno nueva: lo que cambia es **cuándo** se exigen. Tests: tenant en `S3` sin
  bucket → exit 1, mensaje que nombra lo que falta, cero filas escritas; tenant en `LOCAL` → no
  se comprueba nada y el comando sigue. [R3.3, R4.7, D10]

## 5. La fase de avance: el reloj de las dos estancias (D2 pasos 1-5 y 9-11, D3, D4) <!-- panel: PASS 2026-08-16 -->

- [x] 5.1 Crear en `apply_plan` la **segunda mitad**: una fase de avance que corre después de
  `_seed_checklist_template` (`seed_demo.py:457-463`) y antes del único
  `await uow.commit()` (`:465`), dentro de la misma función y la misma transacción, componiendo
  cada caso de uso con `CallerOwnedUnitOfWork()` como hace la plantilla canónica
  `_seed_checklist_template` (`:469-508`). Ni comando aparte ni flag `--advance` (D1). Los
  instantes de cada hecho se derivan del `today` ya anclado al día del tenant (`:413`) y **se le
  pasan a cada caso de uso como `now`** — nunca `datetime.now()`: con `now = hoy`,
  `CHECKIN_WINDOW_OPENED` exige que la reserva entre hoy
  (`backend/app/properties/domain/state_machine.py:229`) y `CHECKIN_TIME_REACHED` exige
  `utc_instant < utc_end` (`:231`), así que los pasos 2, 3 y 9 serían inalcanzables (D3).
  [R2.4, R4.3, D1, D3, D11]

- [x] 5.2 Paso 1 de D2: llevar la estancia `DIRECT` de `PENDING` a `CONFIRMED` con
  `UpdateReservationUseCase`, con el `TENANT_OWNER` como `actor_user_id`. Es el primer paso de la
  fase y no un detalle: `CreateReservationCommand` no acepta `status` a propósito
  (`backend/app/reservations/application/use_cases.py:48-55`) y las cuatro precondiciones de reloj
  exigen `CONFIRMED` o `CHECKED_IN_ESTIMATED` (`state_machine.py:229-236`), así que **la estancia
  DIRECT que el seed lleva sembrando desde el 2026-08-12 está en un estado que el reloj no puede
  avanzar nunca**. Test: tras el comando la DIRECT está `CONFIRMED` y su `RESERVATION_UPDATED`
  está en el timeline. [R2.2, D4]

- [x] 5.3 Pasos 2-4 y 9-10 de D2: invocar `AdvancePropertyStatesUseCase`
  (`backend/app/properties/application/use_cases.py:105-156`) una vez por hecho, con el `now`
  histórico correspondiente y con **actor `SYSTEM`**, cableando los repositorios exactamente como
  hace `_advance` del scheduler (`backend/app/scheduler/tasks.py:105-119`) — incluido el
  `provisioner=ProvisionCleaningTaskUseCase(...)` **sólo** para `CHECKOUT_TIME_REACHED`
  (`tasks.py:86-102`, `:113-117`), que es lo que crea la `CleaningTask` de la estancia pasada en
  vez de insertarla. La secuencia: `CHECKIN_WINDOW_OPENED` y `CHECKIN_TIME_REACHED` en hoy−10,
  `CHECKOUT_TIME_REACHED` en hoy−7, y otra vez `CHECKIN_WINDOW_OPENED` y `CHECKIN_TIME_REACHED` en
  hoy−2. Ninguna escritura directa sobre `properties.current_operational_state`. Tests: REDES11
  recorre `VACANT_READY → AWAITING_CHECKIN → OCCUPIED_ESTIMATED → AWAITING_CLEANING`; existe una
  `CleaningTask` para la estancia pasada creada por el aprovisionamiento y no por el seed;
  **PAJARITOS8 no recibe ningún disparador y sigue en `VACANT_READY`**. [R2.4, R3.1, D2, D3, D8]

- [x] 5.4 Pasos 5 y 11 de D2: llevar la estancia `DIRECT` a `COMPLETED` (en hoy−7, tras el
  checkout) y la `AIRBNB` a `CHECKED_IN_ESTIMATED` (en hoy−2, tras su check-in), por
  `UpdateReservationUseCase` y con el `TENANT_OWNER`. La estancia `BOOKING` (hoy+3) **no se toca**:
  su `status` queda exactamente como lo deja hoy. Enmendar
  `test_none_of_the_three_is_given_a_status_by_hand`
  (`backend/tests/cli/test_seed_demo.py:819-848`), que pinea el comportamiento que este change
  cambia a propósito: pasa a afirmar que ninguna de las tres recibe un `status` **en el momento de
  crearse**, y que las dos que se mueven lo hacen después por `UpdateReservationUseCase` — que es
  un sustituto declarado, porque `reservations` no ofrece hoy operación de check-in ni de cierre.
  [R2.1, R2.2, R2.3, D4]

- [x] 5.5 Enmendar `test_both_properties_are_born_vacant_ready`
  (`backend/tests/cli/test_seed_demo.py:707-720`): sigue siendo cierto que el seed nunca **pasa ni
  escribe** `current_operational_state`, pero ya no es cierto que las dos acaben en
  `VACANT_READY`. El test pasa a afirmar la propiedad que este change conserva —el estado es
  siempre consecuencia de `PropertyStateMachine`, nunca una columna escrita— y a comprobar
  PAJARITOS8 en `VACANT_READY`; el estado final de REDES11 lo pinea el test de secuencia de la 9.1.
  [R2.4]

## 6. El ciclo completo de la limpieza y sus seis fotos (D2 pasos 6-8) <!-- panel: PASS 2026-08-16 -->

- [x] 6.1 Recorrer, en su lugar cronológico (hoy−7, entre los pasos 5 y 9), el ciclo completo de
  la `CleaningTask` que el aprovisionamiento creó en la 5.3, con los casos de uso de
  `backend/app/cleaning/application/use_cases.py`. **Enmendada el 2026-08-16** (DESIGN-CONFLICT del
  panel de la sección 5, resuelto por Jose): **no** se llama a `AssignCleaningTaskUseCase`, porque
  la tarea ya viene asignada — el aprovisionador del checkout auto-asigna cuando hay exactamente
  una limpiadora activa (PRD §11) y dispara él mismo `CLEANER_ASSIGNED`. Lo que hace el ciclo antes
  de empezar es **comprobar que la asignación es la de `SEED_CLEANER_EMAIL` y fallar en voz alta si
  no lo es**, en vez de reasignar (que escribiría un segundo aviso y una segunda fila de auditoría
  por ejecución). El ciclo empieza pues en `AcceptCleaningTaskUseCase` (`:672`),
  `StartCleaningTaskUseCase` (`:756`), los 18 `CompleteChecklistItemUseCase` (`:1200`), las 6
  `UploadCleaningPhotoUseCase` (`:1300`) y `CompleteCleaningTaskUseCase` (`:883`). **El actor de
  todo el ciclo es el cleaner asignado**, no el `TENANT_OWNER`: `accept`, `start`, `complete` y la
  subida exigen que el actor sea el asignado (`backend/app/cleaning/domain/entities.py:200-218`),
  y ése es exactamente el invariante que fuerza el cambio de la regla de actor único. Las fotos
  van por `UploadCleaningPhotoUseCase` y por tanto por el `FileStoragePort` que el `storage_type`
  del tenant resuelva, con los bytes de la 4.2. Tests: la tarea queda en `COMPLETED` con
  `validation_status = PASSED`, hay 18 ítems completados y 6 filas de `cleaning_photos`, y los seis
  objetos existen en el almacenamiento que el tenant resuelva. [R3.1, R3.2, R3.4, R5.2, R5.4, D8]

- [x] 6.2 Idempotencia del tramo, con **una sola comprobación**: si la `CleaningTask` de la
  estancia pasada ya está `COMPLETED`, la fase de limpieza no hace nada — ni asigna, ni completa
  ítems, ni sube fotos. Es lo que impide que una segunda ejecución deje seis objetos huérfanos en
  el bucket. Test: dos ejecuciones seguidas dejan 6 filas de `cleaning_photos` y **6** objetos en
  el almacenamiento, no 12. [R3.5, R4.1, D9]

- [x] 6.3 Recordar las claves de los objetos subidos durante la fase y, al capturar un fallo
  posterior, **enumerarlas en la salida** antes de propagar. `UploadCleaningPhotoUseCase` sólo
  borra compensatoriamente si **su propio** `commit()` falla
  (`cleaning/application/use_cases.py:1425-1436`), y bajo `CallerOwnedUnitOfWork` ese commit no
  ocurre: un fallo posterior revierte las seis filas y deja los seis objetos. Enumerar no es
  limpiar, y el borrado del bucket queda fuera de alcance declarado. Test: un fallo inyectado
  después de las fotos revierte toda la transacción y la salida nombra las seis claves.
  [R4.5, R4.6, D11]

## 7. Las tres incidencias, cada una por su vía (D2 paso 12) <!-- panel: PASS 2026-08-16 -->

- [x] 7.1 Último paso de la fase (instante `hoy`): crear las tres incidencias de §27 con el
  `ReportIncidentUseCase` de la 2.1, con el `TENANT_OWNER` como actor, pasando sólo
  `property_id`, `source`, `title` y `description` de las constantes de la 4.1 — **sin fijar
  `category`, `severity`, `status` ni `ai_classification`**. Idempotencia por `(property_id,
  title)` con los títulos literales de §27, porque `Incident` no tiene `external_id` y el par es
  estable frente al día de ejecución (D9): si las tres ya existen, la fase de incidencias no hace
  nada. Ninguna escritura a `incidents` por vía que no sea un caso de uso de `maintenance`.
  Tests: las tres nacen en `OPEN` sin clasificar y con su `source`; una segunda ejecución no crea
  una cuarta. [R1.1, R1.6, R4.1, R4.2, R5.1, D9]

- [x] 7.2 Clasificar cada una con `ClassifyIncidentUseCase`
  (`backend/app/maintenance/application/use_cases.py:552-577`) **con `actor=None`**, cableada como
  la cablea el job (`backend/app/scheduler/tasks.py:155-172`, con `RuleBasedIncidentClassifier`),
  de modo que `category`, `severity` y `ai_classification` sean resultado del clasificador. El
  actor ausente es lo que hace que el `TimelineEvent` salga con actor `AI` y no reclame a la
  propietaria una clasificación que no hizo (`_record_timeline`, `:380-383`), y es lo que la
  entrada de steering de la 3.1 concede. Tests: las tres quedan clasificadas, su `TimelineEvent`
  lleva actor `AI` y su fila de `AuditLog` de `INCIDENT_CLASSIFIED` va sin `actor_user_id` ni
  `actor_ip`. [R1.2, R5.4, D7]

- [x] 7.3 Contrastar el veredicto: si la `(category, severity)` de cualquiera de las tres no
  coincide con la que §27 declara (constantes de la 4.1), abortar con **exit 1** nombrando la
  incidencia y **ambos** valores —el esperado y el obtenido—, revirtiendo la transacción entera.
  Es la defensa contra la deriva del clasificador: si alguien cambia las keywords, el seed falla
  en rojo en vez de adaptarse en silencio. Test: con el clasificador monkeypatcheado para devolver
  otra categoría, el comando sale con 1, la salida nombra incidencia y valores, y no queda ninguna
  fila. [R1.3, R4.5, R4.7]

- [x] 7.4 Asignar **la incidencia 2** con `AssignIncidentUseCase`
  (`use_cases.py:1026-1050`) al usuario de `SEED_TECHNICIAN_EMAIL`, con el `TENANT_OWNER` como
  actor —que es quien tiene el permiso; el caso de uso ya valida por su cuenta que el técnico
  exista, sea `TECHNICIAN` y esté `ACTIVE` (`:1056-1061`)— dejándola en `ASSIGNED`. Si el actor no
  satisface lo que el caso de uso exige, fallar en voz alta y no degradar a «sin asignar». Las
  incidencias 1 y 3 se quedan en `CLASSIFIED` y **no** en el `OPEN` literal de §27: `classify` es
  la única puerta de salida de `OPEN` y el job de beat las movería igual cada cinco minutos
  (`backend/app/scheduler/schedule.py:34-54`), así que un `OPEN` sembrado no sería un dataset sino
  algo que cambia solo. Tests: la 2 queda `ASSIGNED` al técnico con su SLA abierto; la 1 y la 3
  quedan `CLASSIFIED`. [R1.4, R1.5, R5.3]

## 8. Contrato de consola, idempotencia global, actores y aislamiento <!-- panel: PASS 2026-08-16 -->

- [x] 8.1 **El test de secuencia**, que es la mitigación nombrada del riesgo de D2: afirmar la
  secuencia **completa** de `property_state_transitions` de REDES11 —las **nueve** filas, en orden,
  con su `from_state`/`to_state`— y no sólo el estado final. (**Nueve y no siete**: lo midió el
  panel de QA de la sección 7 contra la base de datos, y cuadra con la propia tabla de D2, que
  enumera nueve pasos con disparador — 2, 3, 4, 6, 7, 8, 9, 10 y 12. El «siete» de la redacción
  original de esta tarea era una cuenta a ojo.) Es la única forma de que la
  permutación mala (incidencias antes que estancias, que deja REDES11 en `MAINTENANCE_REQUIRED` en
  el paso 1 y hace que `(MAINTENANCE_REQUIRED, CHECKIN_WINDOW_OPENED)` no exista en `_POLICY`)
  falle en rojo en vez de llegar al mismo estado final con cinco transiciones menos y un timeline
  vacío. El destino del paso 8 sale por `{READY_FOR_NEXT_GUEST, AWAITING_CHECKIN, VACANT_READY}`
  (`state_machine.py:55`, resuelto por `ContextualStateResolver`), así que el test acepta **el
  conjunto** en esa posición y un valor exacto en las otras **ocho**. Afirmar también que dos
  ejecuciones sobre el mismo día producen el mismo estado final. [R2.5, D2]

  (**«ocho» y no «seis»**: corregido el 2026-08-17 por el panel de QA. Nueve filas menos la
  contextual son ocho, y es lo que el test afirma; el «seis» era el residuo de la cuenta a ojo
  que ya había fallado una vez en esta misma tarea. Verificado contra la base real: la posición
  contextual salió `VACANT_READY`.)

- [x] 8.2 **Hecho dentro de la sección 6** (2026-08-16): las tres claves nuevas del diccionario
  entran con las escrituras que las cuentan, así que dejarlo para la 8 habría dejado dos tests en
  rojo entre secciones. Ampliar `_CONSOLE_COUNTS` (`backend/tests/cli/test_seed_demo.py:474`) y el diccionario
  que `apply_plan` devuelve a **ocho** claves: las cinco de hoy más `incidents`, `cleaning_tasks` y
  `cleaning_photos`. Nada de estados ni de transiciones: la spec dice «un recuento por entidad y
  nada más» y un estado operacional no es una entidad creada (D12). Enmendar
  `test_the_counts_apply_plan_returns_have_the_shape_the_console_prints` (`:522-536`); los dos
  tests de «todo a cero» (`:538`, `:562`) siguen valiendo con ocho. Comprobar que la tabla de
  códigos de salida no gana códigos nuevos: 1 para configuración, precondición y conflicto; 2 para
  fallo de ingest y fallo inesperado. [R4.4, R4.7, D12]

- [x] 8.3 **Hecho dentro de la sección 6** (2026-08-16), por el mismo motivo: es el ciclo de la
  limpieza el que rompe el test del actor único, y una sección no puede cerrarse con la suite en
  rojo. Sustituir `test_the_actor_of_everything_it_writes_is_the_owner`
  (`backend/tests/cli/test_seed_demo.py:321-339`) por la afirmación que este change hace cierta.
  **Este test rompe y el `design.md` no lo nombra**: asserta `set(actors) == {owner.id}` sobre
  **todas** las filas de `audit_logs`, y a partir de ahora hay filas del cleaner y filas sin actor.
  El test nuevo pinea el reparto de D8 por acción: lo que el seed ya escribía hoy y las altas de
  incidencias, la asignación y los `UpdateReservationUseCase` van con el `TENANT_OWNER`; el ciclo
  de la limpieza va con el cleaner asignado; `INCIDENT_CLASSIFIED` va sin actor; y ninguna otra
  acción del flujo de `maintenance` puede ir sin él. [R5.1, R5.2, R5.3, R5.4, D8]

- [x] 8.4 Ampliar el barrido de aislamiento de tenant
  (`backend/tests/cli/test_seed_demo.py:581-673`) a las tres tablas nuevas —`incidents`,
  `cleaning_tasks` y `cleaning_photos`, **estas dos últimas por mecanismos distintos**: la de
  tareas tiene `tenant_id` propio y entra en el bucle de propiedad de las filas, y la de fotos no
  lo tiene, así que se comprueba por su puerto, que hace el join con el padre scopeado— más las
  filas de `cleaning_checklist_completions`,
  `property_state_transitions`, `timeline_events`, `audit_logs` y **`notification_logs`** que la
  fase de avance añade. (`cleaning_checklist_completions` la añadió el panel de tenancy de la
  sección 6, 2026-08-16, y no es una tabla más de la lista: `app/core/db.py` la nombra —en la
  misma frase que `cleaning_photos`— entre las que **no tienen `tenant_id` propio**, «any
  repository touching them must join the scoped parent explicitly and bring its own isolation
  test». El ciclo de la limpieza escribe 18 filas suyas por ejecución.)
  (`notification_logs` la añadió el panel de tenancy de la sección 5, 2026-08-16: el
  aprovisionamiento del checkout auto-asigna la limpieza —hay exactamente una limpiadora
  activa— y eso escribe su aviso de asignación, así que es una quinta tabla nueva que el
  barrido no nombraba. Ampliar también la lista de `_row_counts`, cuyo docstring dice que
  «the list has to match what the isolation test enumerates».) **Sobre sesión sin marcar**: con la
  sesión marcada por `bind_session_to_tenant` el listener de `app/core/db.py` filtra hasta el
  `select` de una columna, así que el test no puede fallar y no prueba nada. Obligatorio por
  `steering/testing.md` (DoD §28.18) y `steering/security.md` regla 1.
  [R4.1, regla 1 de `steering/security.md`]

- [x] 8.5 Idempotencia global y rollback, extendiendo los tests que ya existen: una segunda
  ejecución seguida crea **cero** incidencias, cero tareas de limpieza y cero fotos, no mueve
  ningún estado ya alcanzado, imprime los ocho recuentos a cero y sale con 0. Y un fallo inyectado
  en cualquier punto de la fase de avance revierte la transacción **entera, incluidos los estados
  ya avanzados** — nada de «dataset sembrado pero a medio avanzar». La idempotencia de los estados
  es por construcción y conviene comprobarlo: `AdvancePropertyStatesUseCase` selecciona candidatas
  por estado de origen (`use_cases.py:133-135`) y se traga `NoOperationalStateChangeError`
  (`:212-213`), y `UpdateReservationUseCase` con el valor ya almacenado no escribe ni registra
  nada. [R4.1, R4.3, R4.5, D9, D11]

## 9. Documentación <!-- panel: PASS 2026-08-16 -->

- [x] 9.1 Actualizar `docs/seed-demo.md` con lo que el comando pasa a hacer y con las tres cosas
  que la demo enseña y que nadie debe leer como defectos: **(a)** la demo abre con REDES11 en
  `MAINTENANCE_REQUIRED` —hay huésped dentro, una incidencia `ACCESS`/`HIGH` y un técnico
  asignado— y eso es correcto, no un error del seed: el recorrido completo (ventana de check-in,
  ocupada, mantenimiento requerido) está en el **timeline**, que es donde la demo lo cuenta, y el
  estado operacional es la foto final (OQ2); **(b)** las incidencias 1 y 3 quedan en `CLASSIFIED`
  y no en el `OPEN` de §27, con el porqué; **(c)** `make seed-demo` **depende de red y de
  credenciales cuando el `storage_type` del tenant es `S3`** —el caso de `dev` desde
  `object-storage-provisioning`— y falla antes de escribir si falta configuración. Añadir también
  que el actor deja de ser único y qué invariantes de `cleaning` y `maintenance` lo fuerzan.
  [R1.5, R2.6, R3.3, R5.5]

- [x] 9.2 Nota en `.env.example`, en el bloque `S3_*` que ya existe, de que esas variables pasan a
  ser exigidas también por `make seed-demo` cuando el tenant está en `S3`. **Ninguna variable
  nueva**: lo que cambia es cuándo se exigen (D10). Revisar de paso si el `README.md` de raíz
  necesita algo: el comando no cambia de nombre ni de posición en la secuencia
  `up → bootstrap → seed-demo`, así que probablemente no — dejarlo constatado en la casilla en vez
  de tocarlo por tocarlo. **Constatado (2026-08-16)**: la secuencia no cambia y el README no
  necesitaba nada más, pero sí una línea: la suya enumeraba lo que el comando siembra («dos
  viviendas… tres reservas y la plantilla de limpieza») y esa lista se había quedado corta. Todo lo
  demás sigue delegado en `docs/seed-demo.md`, al que ya enlaza. [R3.3]

- [x] 9.3 **Añadida el 2026-08-17 por el panel de `/sdd:review`**, que la encontró grepeando la
  redacción superada por todo el árbol y no sólo en los ficheros que el diff tocaba. Actualizar
  `infra/environments/dev/RUNBOOK-seed-demo.md`, el procedimiento que un operador sigue en la VM
  de `dev` —es decir justo el camino `S3` que este change estrena—, que se había quedado
  describiendo el comando anterior: su tabla de entidades no tenía las tres nuevas, afirmaba
  «**No crea tareas de limpieza**» (ya no es cierto: crea una y la cierra), y documentaba el
  contrato de consola de **cinco** recuentos en tres sitios (`:32`, el ejemplo literal de `:94` y
  «Los cinco tipos se imprimen incluso a cero» de `:97`). Añadir además las tres consecuencias
  operativas que `docs/seed-demo.md` ya explica —`MAINTENANCE_REQUIRED` es correcto, las
  incidencias 1 y 3 quedan en `CLASSIFIED`, y en `dev` el comando exige red y credenciales— y la
  nota de que una primera ejecución con `0 cleaning_tasks` no es un fallo. Su SQL de limpieza no
  necesitaba nada: ya borraba `incidents`, `cleaning_photos`, `cleaning_checklist_completions` y
  `property_state_transitions`. Las tareas 9.1 y 9.2 no lo cazaron porque nombran
  `docs/seed-demo.md`, `.env.example` y el `README.md` de raíz, y este fichero vive en `infra/`.
  [R4.4, D12]

## 10. Verification

**Re-ejecutada entera el 2026-08-17 sobre la rama rebasada, y eso es el punto.** La primera vez
que se marcaron estas casillas, la rama no tenía ningún commit y su HEAD era antecesor de `main`,
que había avanzado 13 commits: la suite corría en verde contra el `cleaning/` de **antes** del
refactor de `cleaning-completion-evidence-gatherer`, así que acreditaba un árbol que no era el
objetivo de integración. El panel de `/sdd:review` lo levantó, y en efecto el cierre de la
limpieza estaba llamando a `CompleteCleaningTaskUseCase` con los cuatro repositorios que `main`
ya no acepta — un `TypeError` en cuanto se rebasara. Tras el rebase sobre `b42ddec`, arreglar esa
llamada (`evidence=CompletionEvidenceGatherer(...)`, como la cablea `cleaning/api/dependencies.py`)
y **con la base de datos vaciada y remigrada para no heredar el dataset de la ejecución vieja**,
las seis casillas se repitieron y todas dan lo que dicen. Los números medidos están en cada una.

- [x] 10.1 Suite completa del backend en verde desde el worktree:
  `docker compose exec backend uv run pytest` (con el stack parado,
  `docker compose run --rm backend uv run pytest`).
  → **7327 passed, 39 skipped, 0 failed** sobre la rama rebasada (6:14). El uno de más respecto a
  la medición anterior es el test estructural de R1.6 que añadió el panel.
- [x] 10.2 Levantar el stack de este worktree (`make up`) y ejecutar el camino completo de verdad:
  `make bootstrap` y luego `make seed-demo`. Es lo único que verifica el grafo de imports del
  comando y el `bind_session_to_tenant`, que ningún test unitario detecta. Comprobar la salida:
  ocho recuentos, ninguna contraseña.
  → `bootstrap: created 1 tenant(s), 1 config(s), 2 user(s)` y después
  `seed-demo: created 2 users, 2 properties, 3 guests, 3 reservations, 1 checklist_templates,
  1 cleaning_tasks, 6 cleaning_photos, 3 incidents`, exit 0, sin ninguna credencial en la salida.
- [x] 10.3 Contra la base real, comprobar el dataset resultante (MCP `postgres` o `make sh`): tres
  incidencias con su categoría y severidad de §27, la 2 en `ASSIGNED` al técnico y las otras dos en
  `CLASSIFIED`; la estancia AIRBNB en `CHECKED_IN_ESTIMATED` y la DIRECT en `COMPLETED`; la
  `CleaningTask` en `COMPLETED` con `validation_status = PASSED`, sus 18 ítems y sus 6 fotos; y las
  **nueve** filas de `property_state_transitions` de REDES11 en el orden de D2 (nueve y no siete,
  por lo que explica la 8.1). [R1, R2, R3]
  → Todo comprobado por `psql`: `WiFi va lento` WIFI/LOW CLASSIFIED, `Problema con código de
  acceso` ACCESS/HIGH **ASSIGNED**, `Lavadora hace ruido extraño` APPLIANCE/MEDIUM CLASSIFIED;
  DIRECT `COMPLETED`, AIRBNB `CHECKED_IN_ESTIMATED`, BOOKING `CONFIRMED` sin tocar; la tarea
  `COMPLETED`/`PASSED` con 18 ítems y 6 fotos; y las nueve transiciones en el orden exacto de D2
  —`VACANT_READY → AWAITING_CHECKIN → OCCUPIED_ESTIMATED → AWAITING_CLEANING →
  CLEANING_SCHEDULED → CLEANING_IN_PROGRESS → VACANT_READY → AWAITING_CHECKIN →
  OCCUPIED_ESTIMATED → MAINTENANCE_REQUIRED`—, **todas de REDES11**: PAJARITOS8 no recibió ningún
  disparador y quedó en `VACANT_READY`. La posición contextual del paso 8 resolvió a
  `VACANT_READY`, uno de los tres del conjunto que D2 admite.
- [x] 10.4 `make seed-demo` una segunda vez: los ocho recuentos a cero, código de salida 0, ninguna
  fila nueva ni modificada, y **seis objetos en el almacenamiento y no doce** (el `storage_type`
  del stack del worktree es `LOCAL`, así que aquí se comprueba en el volumen; el camino `S3` de
  `dev` es el mismo puerto). [R3.5, R4.1]
  → Los ocho recuentos a cero, exit 0, y las filas intactas (3 incidencias, 1 tarea, 6 fotos, 9
  transiciones). Sobre los objetos, un detalle que conviene no leer mal: el volumen tenía **12**
  ficheros antes y **12** después, y los seis de más son los que quedaron huérfanos al vaciar el
  esquema para esta re-verificación — que es exactamente lo que D11 dice y lo que la
  documentación advierte ahora: tirar la base no toca el almacén. Lo que la casilla afirma es el
  delta, y el delta fue **cero**: la segunda ejecución no subió una séptima foto.
- [x] 10.5 Los dos abortos nuevos contra el stack real: un `tenants.timezone` irresoluble (exit 1,
  nombra columna y valor, no escribe) y un tenant en `S3` sin bucket (exit 1, frase accionable, no
  escribe). [R6.1, R3.3]
  → Zona horaria: con `timezone='Mars/Olympus_Mons'`, «`tenants.timezone` is not a resolvable time
  zone: 'Mars/Olympus_Mons'…» y **exit 1** (medido sobre `python -m`, no sobre `make`, que
  devuelve su propio 2). Almacenamiento: con `storage_type='S3'` y el entorno sin configurar,
  «…this is not configured (**values not echoed**): S3_BUCKET, S3_REGION,
  AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY…» y **exit 1**. Tras los dos abortos, los recuentos y
  los objetos estaban intactos: ninguno escribió nada.
- [x] 10.6 Confirmar que el esquema no cambió:
  `docker compose exec backend uv run alembic check` no propone ninguna migración.
  → «No new upgrade operations detected.»

**Lo que esta sección deliberadamente no incluye**, para que su ausencia no se lea como un olvido:
no hay `make openapi` ni `cd frontend && npm run api:check` porque el change **no añade ningún
endpoint ni cambia la forma de ninguna respuesta** —`ReportIncidentUseCase` es un caso de uso, no
una ruta (`design.md:140-141`)—; no hay claves de `locales/` porque no hay UI; y no hay paso de
lint/typecheck de backend porque el proyecto no tiene ninguno configurado (ni en
`backend/pyproject.toml` ni en `.github/workflows/backend-tests.yml`).

**Y el `make down` no es una tarea de este change**, por lo que ya decidió el gate de
`seed-data-demo` el 2026-08-12: bajar el stack es ciclo de vida del **worktree**, no alcance del
change, y lo hace `/sdd:archive` al retirarlo (`sdd/project.md` §«Stacks huérfanos»). Una casilla
sin marcar aquí bloquearía `LOCAL_VERIFIED` para siempre.

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| R1.1 | 2.1, 4.1, 7.1 |
| R1.2 | 3.1, 7.2 |
| R1.3 | 7.3 |
| R1.4 | 7.4 |
| R1.5 | 7.4, 9.1 |
| R1.6 | 2.1, 2.2, 7.1 |
| R2.1 | 5.4 |
| R2.2 | 5.2, 5.4 |
| R2.3 | 5.4 |
| R2.4 | 5.1, 5.3, 5.5 |
| R2.5 | 8.1 |
| R2.6 | 9.1 |
| R3.1 | 5.3, 6.1 |
| R3.2 | 4.2, 6.1 |
| R3.3 | 4.3, 9.1, 9.2, 10.5 |
| R3.4 | 6.1 |
| R3.5 | 6.2, 10.4 |
| R4.1 | 6.2, 7.1, 8.4, 8.5, 10.4 |
| R4.2 | 7.1 |
| R4.3 | 5.1, 8.5 |
| R4.4 | 8.2 |
| R4.5 | 6.3, 7.3, 8.5 |
| R4.6 | 6.3 |
| R4.7 | 4.3, 7.3, 8.2 |
| R5.1 | 7.1, 8.3 |
| R5.2 | 6.1, 8.3 |
| R5.3 | 7.4, 8.3 |
| R5.4 | 6.1, 7.2, 8.3 |
| R5.5 | 9.1 |
| R6.1 | 1.1, 10.5 |
| R6.2 | 1.2 |
| R6.3 | 1.3 |

**Las tres «spec viva» (R1.5, R2.6, R5.5) las ejecuta `/sdd:archive`**, que es el único que escribe
`sdd/specs/`, a partir de la tabla «Affected specs» del `proposal.md` (`:227-239`). Lo que estas
tareas cubren es la mitad que sí es trabajo de este change: el comportamiento (7.4) y la
documentación de operación (9.1). La excepción es la **regla 9 de `steering/security.md`**, que
**no** es una spec viva sino steering, y por eso sí tiene tarea propia y anterior a su uso (3.1).
