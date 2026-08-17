# Proposal: seed-data-demo-extension

## Why

`seed-data-demo` (archivado el 2026-08-12) dejó el dataset de PRD §27 a medias **a propósito**, y su
proposal se comprometió a que el resto volviera por una entrada propia. Faltan dos cosas, y las dos
faltaban por la misma razón: **no tenían dueño todavía**.

- **Las tres incidencias de §27** (`docs/AutoHostAI_PRD_v5_Claude.md:2257-2284`). Cuando se escribió
  el seed, el único escritor de `Incident` era la vía anónima del portal del huésped, que
  deliberadamente no fija categoría, severidad, clasificación IA ni asignación a técnico. Sembrarlas
  entonces habría sido duplicar invariantes que `maintenance` iba a definir. `maintenance` se archivó
  el 2026-08-15 y ahora es «el único escritor de mutaciones sobre `incidents`»
  (`sdd/specs/maintenance.md:5-11`), así que el `needs:` está satisfecho.
- **Los estados que no se asignan sino que se alcanzan**: la estancia activa en
  `CHECKED_IN_ESTIMATED`, la pasada en `COMPLETED` y su limpieza cerrada con fotos. R4.4 de
  `seed-data-demo` los excluyó explícitamente porque «es el punto exacto donde un seed descuidado
  plantaría a mano el `CHECKED_IN_ESTIMATED` de §27 en vez de dejar que la máquina de estados y el
  scheduler de `celery-jobs` lleguen ahí» (`sdd/specs/seed-data-demo.md:169-173`).

Sin esto la demo no enseña la mitad de lo que existe para enseñar: ninguna incidencia, ninguna
propiedad ocupada, ninguna limpieza cerrada, ninguna foto — y cuatro criterios de la DoD del MVP
(PRD §28.6, §28.7, §28.9) no tienen dataset sobre el que verse.

La entrada arrastra además **tres apuntes acotados** que el panel de `/sdd:review` de
`seed-data-demo` decidió no arreglar dentro de aquel change, y que conviene barrer ahora que este
toca los mismos ficheros (`sdd/roadmap/seed-data-demo-extension.md:5-9`).

**Nota de tamaño**: la entrada declara `size: S`. Al abrirla, no lo es. Toca cinco dominios
(`maintenance`, `reservations`, `properties`, `cleaning`, `integrations`), rompe tres tests que
pinean el comportamiento actual y cambia dos reglas vivas de la spec del seed. Es una **M**, y el
`/sdd:design` debería confirmarlo antes de que el plan de tareas dé por buena una talla que no es.

## What changes

`make seed-demo` deja de entregar un dataset estático y pasa a **hacerlo avanzar por sus propias
vías**. Después de este change, el comando —además de lo que ya siembra— crea las tres incidencias
de §27 y las hace pasar por el clasificador y, la segunda, por la asignación a técnico; lleva la
estancia activa a `CHECKED_IN_ESTIMATED` y la pasada a `COMPLETED`; ejecuta los mismos casos de uso
que el scheduler para que el estado operacional de las dos propiedades sea consecuencia y no una
columna escrita; y recorre entero el ciclo de una limpieza —asignar, aceptar, empezar, 18 ítems,
6 fotos, cerrar— dejando una `CleaningTask` en `COMPLETED` con `validation_status = PASSED` y seis
objetos reales en el almacenamiento que el `storage_type` del tenant resuelva.

Todo eso sigue ocurriendo en **una sola transacción**, con la misma tabla de códigos de salida, y sin
que ninguna escritura toque un modelo ORM directamente. Lo que sí cambia es la regla de «actor único»
(R5) y el estado final de las incidencias 1 y 3 (R1.5), y ambas cosas se registran en la spec viva en
lugar de dejarse como sorpresa.

**Tres decisiones ya tomadas**, porque cambian los requisitos y no el diseño:

1. **Las incidencias 1 y 3 acaban en `CLASSIFIED`, no en el `OPEN` literal de §27.** El par que §27
   describe —`OPEN` **con** categoría y severidad— no existe en el código: `classify` es la única
   operación que escribe esos campos y la única puerta de salida de `OPEN`
   (`backend/app/maintenance/domain/entities.py:107-152`). Y una incidencia sembrada en `OPEN` con
   `ai_classification` a `NULL` no es estable: el job `classify_incidents` corre cada cinco minutos
   y la mueve igual (`backend/app/scheduler/schedule.py:34-54`). Un dataset que cambia solo no es un
   dataset. Se acepta la divergencia y se registra.
2. **`UpdateReservationUseCase` es la vía, y se dice que es un sustituto.** Ni `CHECKED_IN_ESTIMATED`
   ni `COMPLETED` tienen escritor en `reservations`: la máquina de estados de la propiedad los *lee*
   como precondición y nunca los escribe (`backend/app/properties/domain/state_machine.py:229-236`).
   El único escritor invocable es `UpdateReservationUseCase`, y usarlo es honestamente «fijar una
   columna con un caso de uso en medio». Abrir la operación de check-in y de cierre que falta es
   trabajo de `reservations`, no de un seed — queda fuera de alcance y anotado.
3. **Las fotos se suben por el puerto, sea cual sea.** En `dev` el tenant de demo está en `S3` desde
   `object-storage-provisioning`, y `storage_for(S3)` **nunca** cae a `LOCAL`
   (`backend/app/integrations/infrastructure/storage/__init__.py:74-82`). Así que `make seed-demo`
   gana dependencia de red y credenciales cuando el tenant está en `S3`. Es el precio de que en `dev`
   haya una limpieza cerrada de verdad: sin las seis fotos la plantilla del propio seed no deja
   cerrarla.

## Requirements

### R1 — Las tres incidencias de §27, cada una por su vía

**Como** propietaria, **quiero** que la demo muestre tres incidencias reales con su categoría,
severidad y asignación, **para** ver el módulo de mantenimiento operando y no una tabla vacía.

Criterios de aceptación:

1. WHEN el comando se ejecuta sobre un tenant sin incidencias, THE SYSTEM SHALL crear exactamente las
   tres incidencias de PRD §27 con su `property_id`, `source`, `title` y `description` literales, sin
   fijar `category`, `severity`, `status` ni `ai_classification` en el momento de la creación.
2. WHEN cada incidencia ha sido creada, THE SYSTEM SHALL clasificarla con `ClassifyIncidentUseCase`,
   de modo que `category`, `severity` y `ai_classification` sean resultado del clasificador y no
   valores escritos por el seed.
3. IF la clasificación de cualquiera de las tres no coincide con la categoría y la severidad que §27
   declara, THEN THE SYSTEM SHALL abortar con código de salida 1 nombrando la incidencia y ambos
   valores, sin haber escrito nada.
4. WHEN la incidencia 2 está clasificada, THE SYSTEM SHALL asignarla con `AssignIncidentUseCase` al
   usuario de `SEED_TECHNICIAN_EMAIL`, dejándola en `ASSIGNED` — el estado que §27 pide.
5. THE SYSTEM SHALL dejar las incidencias 1 y 3 en `CLASSIFIED` y no en el `OPEN` literal de §27, y
   la spec viva SHALL registrar que `classify` es la única puerta de salida de `OPEN` y que el job de
   beat movería igualmente cualquier incidencia sembrada en `OPEN`.
6. THE SYSTEM SHALL no escribir la tabla `incidents` por ninguna vía que no sea un caso de uso de
   `maintenance`.

### R2 — Las dos estancias que §27 muestra en un estado alcanzado

**Como** manager, **quiero** que la demo tenga una estancia en curso y una terminada, **para** que el
dashboard responda «¿qué pasa y quién tiene la próxima acción?» sobre datos que se parecen a los
reales.

Criterios de aceptación:

1. WHEN el comando siembra la estancia activa (AIRBNB, check-in hoy−2), THE SYSTEM SHALL llevarla a
   `CHECKED_IN_ESTIMATED` mediante `UpdateReservationUseCase`, que emite su `RESERVATION_UPDATED` en
   el timeline.
2. WHEN el comando siembra la estancia pasada (DIRECT, check-out hoy−7), THE SYSTEM SHALL llevarla a
   `COMPLETED` por la misma vía.
3. THE SYSTEM SHALL dejar la estancia próxima (BOOKING, check-in hoy+3) exactamente como la deja hoy,
   sin tocar su `status`.
4. WHEN las estancias están en su estado, THE SYSTEM SHALL hacer avanzar el estado operacional de las
   dos propiedades ejecutando `AdvancePropertyStatesUseCase` con los mismos disparadores que el
   scheduler usa, en lugar de escribir `properties.current_operational_state`.
5. IF el disparador `INCIDENT_HIGH` de la incidencia 2 y los disparadores de estancia compiten por el
   estado de REDES11, THEN THE SYSTEM SHALL fijar el orden de siembra explícitamente y THE SYSTEM
   SHALL aceptar como resultado el que la máquina de estados resuelva, de modo que dos ejecuciones
   sobre el mismo día produzcan el mismo estado.
6. THE SYSTEM SHALL registrar en la spec viva que `reservations` no ofrece hoy una operación de
   check-in ni de cierre, y que `UpdateReservationUseCase` es un sustituto declarado y no la vía
   definitiva.

### R3 — Una limpieza cerrada, con sus seis fotos

**Como** propietaria, **quiero** ver una limpieza completada con su checklist y sus fotos, **para**
comprobar que la evidencia de trabajo llega de verdad y no es una maqueta.

Criterios de aceptación:

1. WHEN existe la `CleaningTask` de la estancia pasada, THE SYSTEM SHALL recorrer su ciclo completo
   —`assign` → `accept` → `start` → los 18 ítems → las 6 fotos → `complete`— usando los casos de uso
   de `cleaning`, y THE SYSTEM SHALL obtenerla de la vía que la crea hoy (el aprovisionamiento del
   checkout) en lugar de insertarla.
2. WHEN el comando sube cada foto, THE SYSTEM SHALL hacerlo por `UploadCleaningPhotoUseCase` —y por
   tanto por el `FileStoragePort` que el `storage_type` del tenant resuelva— con bytes de imagen
   reales que `detect_image_type` acepte.
3. IF el tenant está configurado en `S3` y falta el bucket, la región o las credenciales, THEN THE
   SYSTEM SHALL abortar con código de salida 1 y una frase accionable **antes** de abrir la
   transacción, en vez de fallar a mitad de la siembra.

   **Enmendado el 2026-08-16** (panel de la sección 4, DESIGN-CONFLICT del arquitecto, resuelto por
   Jose): la redacción original decía «bucket, región, **endpoint** o credenciales», y el endpoint
   no puede estar en esa lista. Un `S3_ENDPOINT_URL` vacío es la configuración **correcta** para
   AWS —«*turning it into `None` is what makes "point at AWS" mean configure nothing*»,
   `backend/app/cleaning/api/dependencies.py`—, así que exigirlo aquí rechazaría un despliegue que
   todos los demás caminos del sistema sirven sin problema. El almacén sobre el que corre `dev` sí
   lo necesita, y se entera por la vía ordinaria: `storage_for(S3)` levanta `StorageWriteError`.
4. WHEN el comando termina con éxito **sobre un tenant que crea tareas de limpieza**, THE SYSTEM
   SHALL haber dejado la tarea en `COMPLETED` con `validation_status = PASSED` y seis filas de
   `cleaning_photos` cuyos objetos existen en el almacenamiento.

   **Enmendado el 2026-08-16** (panel de la sección 7, resuelto por Jose): la redacción original no
   contemplaba que no hubiera tarea que recorrer. Si el checkout no aprovisiona ninguna —porque el
   tenant tiene `auto_create_cleaning_task` apagado o no tiene plantilla de checklist, o porque la
   propiedad ni siquiera era candidata en esta ejecución— la fase no hace nada y el comando sigue,
   con `0 cleaning_tasks, 0 cleaning_photos` en la salida. Lo que **sí** aborta con exit 1 es la
   anomalía: que el checkout haya aprovisionado una tarea y no se encuentre. El razonamiento y las
   alternativas rechazadas, en D9.
5. IF la `CleaningTask` de la demo ya está `COMPLETED`, THEN THE SYSTEM SHALL no volver a subir
   ninguna foto, de modo que una segunda ejecución no deje objetos huérfanos en el bucket.

### R4 — Sigue siendo el mismo comando

**Como** operador, **quiero** que la ampliación no cambie el contrato del comando, **para** poder
seguir ejecutándolo tantas veces como quiera sin pensar.

Criterios de aceptación:

1. WHEN el comando se ejecuta dos veces seguidas, THE SYSTEM SHALL crear cero incidencias, cero
   tareas de limpieza y cero fotos en la segunda, y no mover ningún estado ya alcanzado.
2. THE SYSTEM SHALL identificar cada incidencia sembrada por una clave estable que no dependa del día
   de ejecución, declarada en la spec junto a las claves que ya existen.
3. THE SYSTEM SHALL escribir todo lo nuevo dentro de la misma y única transacción que hoy abre
   `apply_plan`, componiendo cada caso de uso con `CallerOwnedUnitOfWork`.
4. WHEN el comando termina con éxito, THE SYSTEM SHALL imprimir un recuento por entidad incluidas las
   nuevas (`incidents`, `cleaning_tasks`, `cleaning_photos`), y nada más.
5. IF cualquier paso falla, THEN THE SYSTEM SHALL revertir la transacción entera, incluidos los
   estados ya avanzados.
6. IF el fallo ocurre después de haber subido fotos, THEN THE SYSTEM SHALL decir en su salida qué
   objetos quedaron en el almacenamiento sin fila que los referencie — el borrado compensatorio de
   `UploadCleaningPhotoUseCase` está atado a su propio `commit`, que bajo `CallerOwnedUnitOfWork` no
   ocurre.
7. THE SYSTEM SHALL mantener la tabla de códigos de salida vigente (1 para configuración,
   precondición y conflicto; 2 para fallo de ingest y fallo inesperado) sin introducir códigos nuevos.

### R5 — El actor deja de ser único, y se declara

**Como** propietaria, **quiero** que el timeline de la demo se lea como el recorrido de varias
personas, **para** que enseñe quién hizo qué y no que todo lo hizo la dueña.

Criterios de aceptación:

1. THE SYSTEM SHALL mantener el `TENANT_OWNER` como actor de todo lo que el comando ya escribe hoy.
2. WHEN el comando recorre el ciclo de la limpieza, THE SYSTEM SHALL actuar como el usuario de
   `SEED_CLEANER_EMAIL`, porque `accept`, `start`, `complete` y la subida de fotos exigen que el
   actor sea el cleaner asignado.
3. WHEN el comando asigna la incidencia 2, THE SYSTEM SHALL usar el `TENANT_OWNER` como actor, y
   THE SYSTEM SHALL fallar en voz alta —exit 1, nombrando la cuenta— si el usuario de
   `SEED_TECHNICIAN_EMAIL` no satisface lo que `AssignIncidentUseCase` exige del técnico (existir,
   ser `TECHNICIAN` y estar `ACTIVE`), sin degradar a «sin asignar».

   **Enmendado el 2026-08-17** (panel de `/sdd:review`): la redacción original pedía «un actor cuyo
   rol satisfaga lo que `AssignIncidentUseCase` exige, y fallar en voz alta si no lo satisface», y
   esa segunda mitad era **vacua**: el caso de uso no exige nada del rol del *actor* —sólo que no
   sea nulo— así que la rama negativa no era alcanzable ni testeable, y un criterio que no puede
   fallar no verifica nada. Lo que sí tiene precondición comprobable es el **técnico**, que es
   quien el caso de uso valida (`use_cases.py`, `InvalidTechnicianError`), y ahí sí hay un test
   que lo pone rojo. El requisito pasa a pedir lo que el sistema puede de verdad garantizar.
4. WHEN cada escritura genera su `TimelineEvent` o su `AuditLog`, THE SYSTEM SHALL dejar constancia
   del actor real que la ejecutó.
5. THE SYSTEM SHALL sustituir en la spec viva la regla «el actor de todo lo que el seed escribe es el
   `TENANT_OWNER`» por «cada escritura lleva el actor que su caso de uso exige», explicando qué
   invariante de `cleaning` y de `maintenance` la fuerza.

### R6 — Los tres barridos que la entrada arrastra

**Como** operador, **quiero** que los apuntes que el panel de `seed-data-demo` dejó pendientes se
cierren aquí, **para** que no sigan viajando de entrada en entrada.

Criterios de aceptación:

1. WHEN `build_plan` valida la configuración, THE SYSTEM SHALL comprobar que `tenants.timezone` es
   una zona resoluble y, si no lo es, abortar con código de salida 1 nombrando la columna y el valor
   rechazado, junto al resto de condiciones de configuración — hoy sale por el catch-all de `main()`
   con la clase de la excepción y «details withheld»
   (`backend/app/cli/seed_demo.py:413`, `:887-906`).
2. THE SYSTEM SHALL corregir el docstring de `ReservationIngestor`
   (`backend/app/integrations/application/ingest.py:1-9`) para que enumere las **tres** rutas de
   ingesta —el sync del PMS, el import CSV y el seed de demo— en las dos frases que hoy dicen «two».
3. THE SYSTEM SHALL cubrir con un test la rama de `SeedIngestError` sin motivos
   (`backend/app/cli/seed_demo.py:736-740`), la única del comando que hoy no ejercita ningún test.

## Out of scope

- **Abrir en `reservations` la operación de check-in y de cierre que falta.** Es la vía correcta y la
  que `field-apps` acabará necesitando, pero es diseño de dominio nuevo y no cabe en un seed. Debería
  ser una entrada propia con `needs: reservations`.
- **Un `POST /incidents`.** `backend/app/maintenance/api/incidents_router.py:11-15` explica por qué no
  existe y qué lo traerá (`messaging-ai`, `IncidentSource.LOCK_ALERT`). Este change escribe por casos
  de uso desde el CLI, no por HTTP.
- **Fotos con contenido representativo** de las viviendas reales. Se usan imágenes sintéticas mínimas
  que `detect_image_type` acepte; sustituirlas por fotos de verdad es material de marketing, no de
  seed.
- **Borrar objetos huérfanos del bucket.** `docker compose down -v` no los toca, y limpiar un bucket
  de objetos que ya no tienen fila es una herramienta de operación propia.
- **Cualquier cambio en la política de la máquina de estados** (`_POLICY`) o en las cadencias del
  scheduler. Si el resultado de R2.5 no gusta, la discusión es de `timeline-state-machine`.
- **El E2E de Playwright que recorra la demo.** Llega con `hardening-release`.
- **Sembrar `owner_approvals`, costes o el ciclo de aprobación de gasto.** §27 no los describe para
  ninguna de las tres incidencias.

## Affected specs

| Spec | Qué le pasa |
|---|---|
| `sdd/specs/seed-data-demo.md` | **Modificar, y bastante**: R4.4 (`:169-173`) deja de ser cierto; la regla de actor único (`:134-141`) se sustituye; «lo que este comando no hace» (`:290-297`) pierde sus dos exclusiones; el contrato de consola (`:238`) gana tres recuentos; idempotencia (`:196`) gana claves nuevas; configuración (`:267`) gana la validación de zona horaria y la de storage |
| `sdd/specs/maintenance.md` | **Modificar**: aparece un segundo escritor de `incidents` fuera de la API — el CLI del seed, componiendo los mismos casos de uso |
| `sdd/specs/reservations.md` | **Modificar**: la frase de `:94-104` sobre las cuatro vías y el «el seed deja `status` en `None` a propósito (R4.4)» deja de describir el sistema |
| `sdd/specs/cleaning.md` | **Modificar**: el cierre de limpieza gana un camino no-HTTP, y con él la constatación de que los casos de uso de `cleaning` son invocables desde un CLI |
| `sdd/specs/file-storage.md` | **Modificar**: el seed pasa a ser un escritor por el puerto, con la consecuencia de que `make seed-demo` depende de red cuando el tenant está en `S3` |
| `sdd/specs/celery-jobs.md` | **Modificar**: `AdvancePropertyStatesUseCase` pasa a invocarse también fuera de beat |
| `sdd/specs/timeline-state-machine.md` | **Revisar**: puede necesitar nota sobre el orden de disparadores de R2.5; si no cambia nada, se deja constancia de que se revisó |

Ninguna spec nueva: este change completa capacidades que ya están documentadas.
