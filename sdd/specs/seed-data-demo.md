# Seed data de demo

## Purpose

`make seed-demo` llena un tenant **ya bootstrapeado** con el dataset de demo de PRD §27: las dos
viviendas reales, las dos cuentas operativas que faltan (`CLEANER` y `TECHNICIAN`), las tres
reservas —pasada, activa y próxima—, la plantilla de checklist de limpieza de PRD §7.10, las tres
incidencias de §27 y una limpieza cerrada con sus seis fotos. Existe
para que un entorno recién levantado se pueda **recorrer** en vez de abrir un dashboard vacío, y
para que cada capability que llega sea demostrable sin escribir SQL a mano.

**No entrega un dataset estático: lo hace avanzar por sus propias vías.** Desde el 2026-08-17 el
comando no se limita a insertar filas en su estado final — reproduce los hechos que llevan hasta
él, en orden cronológico, ejecutando los mismos casos de uso que ejecutarían la API y el scheduler.
La estancia pasada se confirma, entra, sale y deja una limpieza que alguien recorre y cierra; la
activa entra; las incidencias se crean y las clasifica el clasificador. El estado operacional de las
dos viviendas es **consecuencia** de esa cronología y no una columna escrita. Esa es la diferencia
entre una demo que enseña un sistema y una que enseña una captura de pantalla, y es también lo que
hace del comando el llamante más exigente que tienen `cleaning`, `maintenance` y la máquina de
estados: los recorre enteros sin pasar por HTTP.

No crea el tenant: lo **completa**. `make bootstrap` sigue siendo lo único que da la primera
entrada a un entorno nuevo (ver spec `auth-tenancy`), y este comando presupone su resultado.

Desde el 2026-08-24 el dataset llega además a dos superficies que antes quedaban vacías —una
**conversación** con el huésped, procesada por la vía real de entrada, y un **enlace de portal de
huésped** para la estancia activa— y `apply_plan` tiene un segundo llamante: el comando del tenant de
demostración (ver [`demo-tenant.md`](demo-tenant.md)), que lo reutiliza tal cual en vez de escribir un
seed propio. Eso convierte a este módulo en la pieza compartida por los dos tenants del entorno, y es
la razón de que varias de sus decisiones se lean como parametrizaciones en lugar de constantes.

## Requirements

### Un comando de seed reproducible

- WHEN el operador ejecuta `make seed-demo` sobre una base migrada cuyo tenant ya existe, THE
  SYSTEM SHALL crear las propiedades, las cuentas, las reservas, los huéspedes y la plantilla en
  alcance, e imprimir un recuento por tipo de entidad creada.
- THE SYSTEM SHALL imprimir **los cinco tipos de entidad incluso a cero**, porque «created 0 users,
  0 properties…» es lo que le dice al operador que una segunda ejecución no hizo nada; una línea
  que omitiera los ceros sería indistinguible de un trabajo hecho a medias.
- WHEN el comando se ejecuta una segunda vez sobre la misma base, THE SYSTEM SHALL no crear
  ninguna fila nueva, no modificar ninguna existente, y terminar con código 0.
- IF el tenant nombrado por `BOOTSTRAP_TENANT_NAME` no existe, THEN THE SYSTEM SHALL abortar con
  `SeedPreconditionError` y código 1, nombrando `make bootstrap`, **sin escribir nada**. Es una
  propiedad de la secuencia y no una promesa: el tenant se resuelve antes de cualquier escritura.
- THE SYSTEM SHALL imprimir únicamente recuentos e identificadores — nunca contraseñas, hashes ni
  tokens.
- THE SYSTEM SHALL validar en `build_plan()` toda la configuración **que se puede juzgar sin tocar
  la base de datos** —las variables de entorno y la colisión de los dos correos `SEED_*`—,
  reportando de una vez todas las ausentes (mismo contrato que `bootstrap.build_plan`).
- THE SYSTEM SHALL juzgar en `apply_plan()`, **tras resolver el tenant y antes de la primera
  escritura**, las dos condiciones de configuración que viven en la base de datos: que
  `tenants.timezone` sea una zona resoluble y que un tenant configurado en `S3` tenga con qué
  escribir. La garantía que ofrecen no es «sin transacción abierta» sino **«nada escrito»**, que es
  la que importa; ponerlas en `build_plan` habría exigido que ese paso abriera sesión, y dejarlas
  donde caerían solas las mandaba al catch-all con la clase de la excepción y sin remedio.
- THE SYSTEM SHALL validar también `BOOTSTRAP_TENANT_NAME` ahí, aunque no sea una de las seis
  variables propias: es lo que nombra al tenant a completar, así que vacía es *configuración que
  falta* y no *un tenant que no existe* — el mensaje de la precondición mandaría al lector a
  `make bootstrap` por una variable que nunca rellenó.
- THE SYSTEM SHALL no formar parte de `make up`, y THE SYSTEM SHALL NOT ser una migración de datos de
  Alembic — necesita valores que elige una persona.
- `make seed-demo` sigue **fuera de todo workflow de CD**, y sus seis variables sin default son lo que
  lo sostiene. Lo que sí corre programado desde el 2026-08-24 es `apply_plan`, reutilizado por el
  comando del tenant de demostración, que un workflow con `schedule:` ejecuta a diario. La diferencia
  importa y no es formal: ese llamante no toma del entorno ni el tenant ni las cuentas —los lleva en
  constantes— y trae sus propios rechazos, así que lo que llegó a CD es la *función*, nunca el comando
  parametrizado por `.env`. Ver [`demo-tenant.md`](demo-tenant.md).

### La regla de escritura: caso de uso, si no entidad y puerto, nunca modelo ORM

- THE SYSTEM SHALL escribir **por el caso de uso** cuando exista uno que haga lo que el seed
  necesita; WHERE no exista, THE SYSTEM SHALL escribir **por la entidad de dominio y su puerto**; y
  THE SYSTEM SHALL NOT escribir nunca por un modelo ORM (`session.add(Model(...))`).
- Es lo que impide que el seed se convierta en un segundo escritor con su propia copia de los
  invariantes. Lo que el seed no puede usar no es «el dominio» sino la envoltura HTTP de un caso de
  uso concreto; bajar un escalón conserva la validación de rol, las guardas de cross-tenant y la
  traducción de índices únicos que un insert crudo se salta.

### Scope de tenant en un comando

- THE SYSTEM SHALL importar `app.core.models_registry` por su efecto colateral, porque un comando
  tiene su propio grafo de imports y sin todos los modelos registrados SQLAlchemy no resuelve las
  claves ajenas. Ningún test unitario detecta su ausencia —el `conftest` de la suite importa el
  registro siempre—, así que sólo ejecutar el comando de verdad lo comprueba.
- THE SYSTEM SHALL llamar `bind_session_to_tenant(session, tenant.id)` antes de cualquier lectura
  ORM con scope, porque un comando no pasa por `get_authenticated_request`, que es quien
  normalmente marca la sesión.
- THE SYSTEM SHALL hacer las dos búsquedas globales de correo **antes** de marcar la sesión. «Sin
  scope» es una propiedad de la *sentencia*, no del método: una vez marcada, el listener de
  `app/core/db.py` añade la cláusula de tenant también a `find_by_email_globally`, que devolvería
  `None` para el correo de otro tenant y convertiría el rechazo explicado en un `IntegrityError`.
  El seed es por eso el primer llamante que **lee sin marcar y marca a media ejecución**, anotado
  en el límite 2 del listener.
- THE SYSTEM SHALL cerrar todo el trabajo en **una sola transacción**, propiedad de `apply_plan`:
  los casos de uso que compone reciben `CallerOwnedUnitOfWork`, de modo que ninguno commitea por su
  cuenta.

### Las dos propiedades por su vía canónica

- WHEN el seed corre, THE SYSTEM SHALL crear `Redes 11`/`REDES11` (4 huéspedes, 2 dormitorios, 1
  baño) y `Pajaritos 8`/`PAJARITOS8` (2 huéspedes, 1 dormitorio, 1 baño), ambas en Madrid, con
  entrada por defecto a las 15:00 y salida a las 11:00, invocando `CreatePropertyUseCase`.
- THE SYSTEM SHALL no pasar `current_operational_state` — `CreatePropertyCommand` no tiene ese
  campo —, de modo que ambas nacen en `VACANT_READY` por el default del esquema y la columna queda
  donde `PropertyStateMachine` la gobierna.
- THE SYSTEM SHALL dejar `country`/`timezone` en los defaults del comando (`ES`/`Europe/Madrid`),
  que es lo que §27 dice, y `postal_code` en `None`, que §27 no da.
- THE SYSTEM SHALL NOT fijar `pms_external_id`. Ponerlo habría hecho demoable `make pms-sync` del
  tirón, al precio de que ese sync importara las dos reservas del `MockPMSAdapter` —con fechas
  desplazadas por la ventana— encima de las tres del seed, y reportara los dos errores que el mock
  emite a propósito. Quien quiera demostrar el sync lo pone a mano por `PATCH`.
- WHERE el tenant ya contiene una propiedad con ese `internal_code`, THE SYSTEM SHALL dejarla
  intacta y no crear una segunda.
- THE SYSTEM SHALL no pasar `actor_ip`: esto es un comando, no una petición.

### Los cuatro roles presentes y operativos

- WHEN el seed corre, THE SYSTEM SHALL dejar el tenant con las cuatro cuentas de rol
  (`TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`) presentes y operativas: **dos que
  ya existían y dos nuevas**.
- THE SYSTEM SHALL resolver al `TENANT_OWNER` y al `PROPERTY_MANAGER` **por rol**
  (`UserFilters(role=...)`), no por correo. Los correos de esas dos cuentas los eligió quien
  bootstrapeó el entorno en `BOOTSTRAP_OWNER_EMAIL`/`BOOTSTRAP_MANAGER_EMAIL`: sembrar los de §27 a
  ciegas crearía una quinta cuenta y un segundo `TENANT_OWNER` en cuanto no coincidieran. Los
  correos de §27 para esas dos son **lo que el operador pone en su `.env`**, no algo que el comando
  imponga — y así lo dicen `README.md` y `docs/seed-demo.md`.
- IF falta el owner o el manager del tenant, THEN THE SYSTEM SHALL abortar con código 1 y la misma
  explicación que la precondición del tenant.
- THE SYSTEM SHALL elegir la cuenta por el orden de `list` (`name`, con `id` de desempate) y no
  arbitrariamente: `assert_tenant_keeps_an_owner` garantiza **al menos** un owner, no exactamente
  uno, y lo que hace falta es que dos ejecuciones atribuyan sus escrituras a la misma persona.
- THE SYSTEM SHALL crear las dos cuentas nuevas con `User.create(..., must_change_password=False)`
  seguido de `SqlAlchemyUserRepository.add`, y THE SYSTEM SHALL NOT usar `CreateUserUseCase`: ése
  genera la contraseña y por eso marca el flag. Lo incompatible con una demo utilizable no es el
  dominio —`must_change_password` tiene default `False` en la entidad, precisamente para las vías
  cuya contraseña elige una persona— sino ese caso de uso.
- THE SYSTEM SHALL tomar la contraseña de cada cuenta nueva de una variable de entorno
  **obligatoria**, y el árbol de código SHALL NOT contener ningún valor por defecto para ellas.
- THE SYSTEM SHALL normalizar el correo en `build_plan` además de en el repositorio: guardado con
  mayúsculas, la búsqueda del login no encontraría la cuenta y no podría entrar.
- IF `SEED_CLEANER_EMAIL` y `SEED_TECHNICIAN_EMAIL` son la misma dirección, THEN THE SYSTEM SHALL
  rechazarlo en `build_plan` con código 1, **sin echar el valor**. No es cosmética: las dos
  búsquedas se indexan por correo, así que una dirección las colapsa en una entrada que responde
  `None` a las dos, el bucle inserta dos veces y el segundo `INSERT` muere dentro de
  `uq_users_lower_email` — y `StatementError.__str__` de SQLAlchemy anexa la sentencia **con sus
  parámetros**, uno de los cuales es el hash bcrypt de una cuenta viva.
- IF un correo de las cuentas nuevas ya existe **en otro tenant**, THEN THE SYSTEM SHALL abortar con
  `SeedConflictError` y código 1, nombrando el rol y las dos variables, sin echar la dirección. El
  índice único global rechazaría el insert igualmente: la comprobación existe **por el mensaje**, no
  por el invariante.
- THE SYSTEM SHALL juzgar **las dos direcciones antes de la primera escritura**, y no una a una
  dentro del bucle: un `SEED_CLEANER_EMAIL` limpio seguido de un `SEED_TECHNICIAN_EMAIL` ajeno
  flushearía un usuario y su fila de auditoría antes de rechazar, dejando el «sin escribir nada» a
  merced del rollback en vez de ser una propiedad.
- WHERE una cuenta con ese correo ya existe en el tenant, THE SYSTEM SHALL dejarla intacta,
  **incluida su contraseña actual**.
- THE SYSTEM SHALL escribir la fila de `AuditLog` (`USER_CREATED`, entidad `USER`) del alta de cada
  cuenta nueva, con el `ChangeSet` de `email` y `role` y `password` **redactado**, dentro de la
  misma transacción. Es la única asignación de rol de la ejecución, y `reset_password.py` ya sienta
  el precedente de que un comando escribe la suya. Las altas de propiedad y de reserva traen la
  suya de serie porque sus casos de uso ya la escriben.

### Cada escritura lleva el actor que su caso de uso exige

Hasta el 2026-08-17 la regla era «el actor de todo lo que el seed escribe es el `TENANT_OWNER`», y
era cierta porque el comando sólo escribía cosas que el owner puede escribir. En cuanto el dataset
incluye **trabajo de campo**, un actor único deja de ser posible sin saltarse invariantes ajenos.

- THE SYSTEM SHALL atribuir al `TENANT_OWNER`, resuelto por rol, las propiedades, las reservas, los
  `TimelineEvent` del ingest, las filas de `AuditLog` de las altas de cuenta, los cambios de
  `status` de reserva y el alta y la asignación de incidencias. Se elige el owner porque su
  existencia es un invariante del tenant mientras que un manager se puede dar de baja.
- THE SYSTEM SHALL actuar como **la cuenta de `SEED_CLEANER_EMAIL`** durante todo el ciclo de la
  limpieza. No es una preferencia: `accept`, `start`, la subida de cada foto y el cierre exigen que
  el actor **sea la limpiadora asignada**, así que el owner no puede recorrerlo.
- THE SYSTEM SHALL disparar los avances de estado operacional como **`SYSTEM`**, que es lo que hace
  el scheduler por esos mismos disparadores.
- THE SYSTEM SHALL clasificar **sin actor**, de modo que el timeline de la demo enseñe a la IA
  clasificando y no a la propietaria. Es una excepción concedida por su nombre en la regla 9 de
  `steering/security.md`, y lo que la concede es que no hay **decisión** humana detrás: la categoría
  y la severidad las pone el clasificador sobre un texto que ya estaba escrito.
- THE SYSTEM SHALL NOT usar nunca la cuenta de `SEED_TECHNICIAN_EMAIL` como actor: es el
  **destinatario** de una asignación, no quien ejecuta nada.
- THE SYSTEM SHALL resolver al `PROPERTY_MANAGER` aunque no lo use como actor de ninguna escritura:
  su única función es que el comando falle si el tenant no lo tiene.
- WHEN cada escritura genera su `TimelineEvent` o su `AuditLog`, THE SYSTEM SHALL dejar constancia
  del actor **real** que la ejecutó. Consecuencia asumida, que no ha cambiado: las altas que hizo un
  comando siguen atribuidas al owner. Es una propiedad del dataset de demo.

### Las tres reservas, cada una por la vía que su canal permite

- THE SYSTEM SHALL fechar las tres estancias relativas a **hoy** conforme a §27: `DIRECT`
  hoy−10 → hoy−7 (pasada), `AIRBNB` hoy−2 → hoy+1 (activa), `BOOKING` hoy+3 → hoy+7 (próxima).
- THE SYSTEM SHALL calcular «hoy» como el día del calendario **del tenant**
  (`at.astimezone(ZoneInfo(tenant.timezone)).date()`), no el de UTC. Son días distintos durante
  parte de cada noche: entre las 00:00 y las 01:00–02:00 de Madrid, UTC va todavía en el día
  anterior, así que las tres estancias nacían un día antes del calendario local y la «activa» hacía
  checkout a las 11:00 de esa misma mañana en lugar del día siguiente.
- THE SYSTEM SHALL calcular ese ancla **una sola vez** y pasarlo como parámetro a los tres
  ayudantes que fechan, para que una ejecución lenta que cruce la medianoche no reparta el dataset
  entre dos días.
- THE SYSTEM SHALL persistir todas las marcas de tiempo (`created_at`, `AuditLog`,
  `TimelineEvent`) en **UTC**: sólo el día del calendario es local.
- THE SYSTEM SHALL crear la reserva `DIRECT` de Pedro López invocando `CreateReservationUseCase`,
  con `external_channel_id = SEED-DIRECT-1`.
- THE SYSTEM SHALL crear las de canal `AIRBNB` y `BOOKING` —ambas sobre `REDES11`— por
  `ReservationIngestor.ingest`, con un `resolve_property` que busca por `internal_code` (el mismo
  resolver que el import de CSV) y `source="seed"`. `CreateReservationCommand.__post_init__`
  **rechaza** todo canal fuera de `MANUAL_CHANNELS`, y esa negativa no es un obstáculo que rodear:
  un canal OTA significa que la estancia vino de un feed y lleva `external_pms_id`, que es la clave
  con la que el siguiente sync la reconoce.
- THE SYSTEM SHALL NOT pasar la `DIRECT` por el ingest: le pondría un `external_pms_id`, que es
  mentira porque no viene de ningún PMS.
- THE SYSTEM SHALL no asignar `status` **al crearlas**. En la `DIRECT` es gratis
  (`CreateReservationCommand` no tiene el campo); en las OTA el DTO sí lo tiene y dejarlo `None` es
  deliberado — es el punto exacto donde un seed descuidado plantaría a mano el
  `CHECKED_IN_ESTIMATED` de §27 en vez de dejar que la máquina de estados llegue ahí. Los estados
  que §27 pide se **alcanzan** después, en la fase de avance, y por sus casos de uso.
- THE SYSTEM SHALL no fijar `net_amount` en los DTO: los €297.50 de §27 son
  `gross_amount - ota_commission`, que `net_amount_from` deriva dentro del ingestor.
- THE SYSTEM SHALL registrar los tres huéspedes por la vía canónica de su dominio y **nunca**
  escribiendo `GuestModel`. Los dos de OTA entran por `_link_guest` dentro del ingestor; el de la
  `DIRECT` se crea antes, con `Guest(...)` + `SqlAlchemyGuestRepository.add`, porque
  `CreateReservationUseCase` sólo comprueba que el `guest_id` exista y **no crea huéspedes**. El
  orden importa: `add` hace `flush` y el único `commit` cierra las dos escrituras, así que una
  reserva que falle se lleva a su huésped y no deja un huérfano.
- THE SYSTEM SHALL dejar a Pedro López **sin correo**: §27 no le da ninguno e inventárselo sería
  deriva del dataset.
- THE SYSTEM SHALL contar los huéspedes nuevos **antes** del ingest y a través del puerto, no
  inferirlos de `report.created`: `_link_guest` reutiliza el huésped que coincide por correo, así
  que «un huésped por reserva nueva» es cierto del dataset de hoy y no de la operación.
- IF el ingest devuelve filas saltadas o con error, THEN THE SYSTEM SHALL fallar con
  `SeedIngestError` y código 2, **imprimiendo los motivos**. `ingest` está construido para
  sobrevivir a una fila mala y seguir —correcto para un CSV que subió una persona, falso para un
  dataset que este módulo escribió él mismo—, y el silencio imprimiría recuentos afirmando una
  siembra que no ocurrió.
- WHERE `report.skipped` es distinto de cero sin ningún `RowError` detrás, THE SYSTEM SHALL indicar
  los recuentos en lugar de un mensaje vacío: un fallo en voz alta que no da ningún motivo es la
  única forma que esta excepción existe para evitar.

### La fase de avance: el reloj se reproduce, no se adelanta

- THE SYSTEM SHALL pasar a cada avance el `now` **del hecho que representa**, derivado del mismo
  ancla de día del tenant que fecha las estancias, y NEVER SHALL avanzar el reloj del sistema ni
  relajar ninguna precondición de la máquina de estados. Es obligatorio y no estético: con
  `now = hoy`, `CHECKIN_WINDOW_OPENED` de una estancia que entró hace diez días es un contexto
  incompatible y `CHECKIN_TIME_REACHED` de la pasada exige un instante anterior a su fin, que hoy no
  lo es. Sin `now` histórico esos pasos son **inalcanzables**.
- Efecto secundario buscado: las transiciones y los eventos de timeline quedan fechados cuando el
  hecho ocurrió, así que la demo se lee como una cronología y no como un volcado instantáneo.
- THE SYSTEM SHALL llevar la estancia `DIRECT` de `PENDING` a `CONFIRMED` antes de cualquier
  disparador. **Es un hallazgo del sistema y no una necesidad del seed**: una reserva manual nace
  `PENDING` porque `CreateReservationCommand` no acepta `status`, y las cuatro precondiciones de
  reloj exigen `CONFIRMED` o `CHECKED_IN_ESTIMATED`, así que la estancia que este comando lleva
  sembrando desde el 2026-08-12 estaba en un estado que el reloj **no podía avanzar nunca**. Queda
  anotado en [`reservations.md`](reservations.md), que es de quien es el hueco.
- THE SYSTEM SHALL llevar la estancia pasada a `COMPLETED` **después** del checkout y la activa a
  `CHECKED_IN_ESTIMATED`, ambas con `UpdateReservationUseCase`, y SHALL declarar esa vía como un
  **sustituto**: `reservations` no ofrece hoy operación de check-in ni de cierre, la máquina de
  estados lee esos dos estados como precondición y nunca los escribe, y fijar la columna con un caso
  de uso en medio es lo más honesto que se puede hacer hasta que esa operación exista. Abrirla es
  trabajo de `reservations` y queda fuera de alcance.
- THE SYSTEM SHALL dejar la estancia próxima (`BOOKING`) **intacta**, sin tocar su `status`.
- THE SYSTEM SHALL ejecutar los avances con `AdvancePropertyStatesUseCase` y los mismos
  disparadores que usa el scheduler, en lugar de escribir `current_operational_state`, y SHALL
  pasarle el aprovisionador de limpieza **sólo** en el disparador de checkout — que es como está
  cableado el job.
- THE SYSTEM SHALL fijar el orden de los disparadores como parte de su contrato, y ese orden SHALL
  ser el cronológico de los hechos. **La permutación que se rechaza tiene nombre**: sembrar las
  incidencias antes que las estancias deja la vivienda en `MAINTENANCE_REQUIRED`, desde donde el
  par con `CHECKIN_WINDOW_OPENED` no existe en la matriz; el dataset acabaría en el mismo estado
  final con cinco transiciones menos y un timeline vacío, porque el rechazo se traga como aviso. Es
  el fallo silencioso perfecto, y por eso la fase de incidencias va **la última**.
- THE SYSTEM SHALL contar las tareas de limpieza a partir del informe del checkout —las transiciones
  que sí aprovisionaron tarea— y no de la fase de limpieza, que no crea ninguna.
- Consecuencia aceptada, que la documentación debe decir con todas las letras para que nadie la lea
  como un defecto: **la demo abre con REDES11 en `MAINTENANCE_REQUIRED`**, porque hay un huésped
  dentro y una incidencia de severidad alta. El recorrido completo sí queda en el timeline, que es
  donde la demo lo cuenta; el estado operacional es la foto final, no la historia. La única palanca
  para evitarlo sería contradecir §27 bajando la severidad de esa incidencia. PAJARITOS8 no recibe
  ningún disparador —no tiene estancias y su incidencia es de severidad media, que no mapea a
  ninguno— y se queda en `VACANT_READY`.

### El ciclo de la limpieza, recorrido por la limpiadora

- THE SYSTEM SHALL **buscar** la `CleaningTask` de la estancia pasada en lugar de insertarla: la
  crea el aprovisionador del checkout, que es la vía que la crea en producción.
- THE SYSTEM SHALL NOT asignarla. PRD §11 auto-asigna cuando el tenant tiene exactamente una
  limpiadora activa —y el dataset de §27 tiene exactamente una—, así que el aprovisionador ya la
  asignó y disparó su transición. Llamar además a la asignación escribiría un segundo aviso y una
  segunda fila de auditoría por ejecución.
- WHERE la tarea no está asignada a la cuenta de `SEED_CLEANER_EMAIL`, THE SYSTEM SHALL abortar con
  código 1 diciendo que esa asignación se hace sola en el checkout cuando hay una única limpiadora
  activa, en vez de reasignarla: el seed no arregla un roster que no es suyo.
- WHEN la tarea existe y no está cerrada, THE SYSTEM SHALL recorrerla entera —aceptar, empezar, los
  18 ítems del checklist, las 6 fotos, cerrar— con los casos de uso de `cleaning`, dejándola en
  `COMPLETED` con validación `PASSED`.
- THE SYSTEM SHALL subir cada foto por el caso de uso de subida, y por tanto por el puerto de
  almacenamiento que el `storage_type` del tenant resuelva, con bytes de imagen reales que la
  detección de tipo acepte. **Consecuencia asumida**: `make seed-demo` gana dependencia de red y
  credenciales cuando el tenant está en `S3`, porque ese adaptador nunca cae a disco local. Es el
  precio de que en `dev` haya una limpieza cerrada de verdad — sin las seis fotos, la plantilla que
  el propio seed siembra marca las seis como obligatorias y la limpieza no cierra.
- IF el checkout **aprovisionó** una tarea y luego no se encuentra, THEN THE SYSTEM SHALL abortar
  con código 1: es un dataset que nadie puede explicar.
- IF el checkout **no aprovisionó ninguna** —porque el tenant no crea limpiezas automáticamente o no
  tiene plantilla de checklist, o porque la propiedad ni siquiera era candidata en esta ejecución—,
  THEN THE SYSTEM SHALL no hacer nada en esta fase y **continuar** con el resto del dataset,
  contándolo como `0 cleaning_tasks, 0 cleaning_photos`. Eso es configuración del tenant, y
  rechazarla sería que el seed decida algo que no le toca; el aprovisionador dice de sí mismo que
  devuelve «nada» por cualquier razón ordinaria y deja que el llamante lo cuente.
- IF la tarea ya está `COMPLETED`, THEN THE SYSTEM SHALL no volver a subir ninguna foto. **Una sola
  pregunta cubre la tarea, los 18 ítems y las 6 fotos**, y es lo que impide que una segunda
  ejecución deje seis objetos huérfanos en el bucket: no hay clave estable por foto que pudiera
  hacerlo foto a foto.

### Las tres incidencias de §27, cada una por su vía

- WHEN el tenant no tiene ya las tres, THE SYSTEM SHALL crearlas con `ReportIncidentUseCase`
  ([`maintenance.md`](maintenance.md)) con su propiedad, su `source` y sus textos literales de §27,
  **sin fijar** `category`, `severity`, `status` ni clasificación IA: nacen en `OPEN` con los
  defaults de la entidad.
- THE SYSTEM SHALL escribir `title` y `description` desde **constantes del módulo** y nunca
  componiendo texto. La excepción 2 de la regla 11 de `steering/security.md` —la que concede la
  prosa de quien reporta— dice de sí misma que **no autoriza a un escritor nuestro**, y el seed es
  un escritor nuestro. La salida no es pedir una excepción nueva sino no necesitarla. La forma
  cerrada es **disciplina de este llamante** y no está impuesta en código.
- WHEN cada incidencia está creada, THE SYSTEM SHALL clasificarla con el clasificador basado en
  reglas y sin actor, de modo que categoría, severidad y clasificación IA sean **resultado** y no
  valores escritos por el seed.
- IF la clasificación de cualquiera no coincide con lo que el dataset declara, THEN THE SYSTEM SHALL
  abortar con código 1 nombrando la incidencia y ambos pares de valores, sin dejar nada escrito. Un
  clasificador que falla o que queda bajo su umbral de confianza deja la incidencia en `OPEN` con
  los defaults, así que cae por este mismo camino: el comando no distingue «clasificó distinto» de
  «no clasificó», y no le hace falta — las dos cosas significan que el dataset no es lo que dice.
- THE SYSTEM SHALL asignar al técnico **la incidencia de severidad alta**, y SHALL decidirlo por la
  severidad y no por la categoría, dejándola en el `ASSIGNED` que §27 pide.
- IF la cuenta de `SEED_TECHNICIAN_EMAIL` existía ya y no es un `TECHNICIAN` activo, THEN THE SYSTEM
  SHALL abortar con código 1 nombrando la variable, sin degradar a «sin asignar». No es un caso
  hipotético por una razón concreta: si la dirección no existe, el seed **la crea** con el rol
  correcto; el fallo sólo es alcanzable sobre una cuenta preexistente, que el seed deja intacta por
  la misma regla que protege su contraseña.
- THE SYSTEM SHALL dejar las otras dos en `CLASSIFIED` y **no** en el `OPEN` literal de §27. El par
  que §27 describe —`OPEN` *con* categoría y severidad— no existe en el código: `classify` es la
  única operación que escribe esos campos y la única puerta de salida de `OPEN`. Y una incidencia
  sembrada en `OPEN` no sería estable, porque el job de clasificación la movería en su siguiente
  tick. **Un dataset que cambia solo no es un dataset**, así que se acepta la divergencia y se
  registra aquí.
- THE SYSTEM SHALL NOT escribir la tabla de incidencias por ninguna vía que no sea un caso de uso de
  `maintenance`.

### La conversación, procesada por la vía real de entrada

- WHEN el seed corre, THE SYSTEM SHALL crear una conversación anclada a la **estancia activa** y a su
  huésped mediante `CreateConversationUseCase`, y THE SYSTEM SHALL hacer entrar cada mensaje del
  huésped por `ProcessInboundGuestMessageUseCase`, separados un minuto entre sí.
- THE SYSTEM SHALL NOT escribir las filas de `messages` directamente: un hilo insertado a mano parece
  correcto y no ejercita nada — ni la clasificación de intención, ni la política de escalado, ni la
  respuesta automática, que es justo lo que la conversación existe para enseñar. Es la misma regla de
  escritura que el resto del comando, aplicada a `messaging-ai`.
- THE SYSTEM SHALL usar `MockAIAdapter` —el mismo adaptador que inyecta el router real—, de modo que
  la siembra **no dependa de red ni de credenciales** de ningún proveedor de IA.
- THE SYSTEM SHALL elegir dos textos constantes que caigan en las intenciones `WIFI` y `EMERGENCY`,
  **pineadas por test** contra el intent que deben producir, porque son las que ejercitan las dos
  ramas del pipeline: la respuesta con plantilla y el escalado a una persona. El pineado no es celo:
  `MockAIAdapter.generate_response` lanza `KeyError` a propósito para tres intents, así que un texto
  que derivara a la rama equivocada rompería el seed.
- THE SYSTEM SHALL escribir en el idioma que la conversación declara.

### El enlace del portal de huésped, emitido una sola vez

- WHERE el llamante **pide** el enlace, THE SYSTEM SHALL emitir un token de portal para la estancia
  activa mediante `IssueGuestAccessTokenUseCase`, persistiendo únicamente su digest, y SHALL devolver
  la URL en claro al llamante — que es la única vez que ese valor existe.
- WHERE el llamante **no** lo pide, THE SYSTEM SHALL no mintar ningún token. Es lo que hace
  `make seed-demo` sobre el tenant de trabajo: el enlace es una necesidad del tenant de demostración,
  no del dataset, y mintar un token de acceso anónimo en el entorno del equipo sería regalarlo.
- WHERE la estancia ya tiene un token vivo y no revocado, THE SYSTEM SHALL no acuñar un segundo, de
  modo que una segunda ejecución no invalide el enlace ya publicado. En el reset del tenant de
  demostración eso no se nota, porque su fase de borrado limpia `guest_access_tokens` antes.

### Idempotencia por identidad estable

- THE SYSTEM SHALL identificar cada entidad por una clave que **no depende del día**: las
  propiedades por `internal_code`; las cuentas por el correo normalizado; las reservas OTA por
  `external_pms_id` (`SEED-AIRBNB-1`, `SEED-BOOKING-1`); la `DIRECT` por `external_channel_id`
  (`SEED-DIRECT-1`), buscado paginando `ReservationRepository.list` filtrado por su propiedad; la
  plantilla por «el tenant ya tiene al menos una»; las **incidencias** por el par
  `(property_id, title)` con los títulos literales de §27, paginando el listado del tenant; y la
  **limpieza con sus 18 ítems y sus 6 fotos** por «la tarea de la estancia pasada ya está
  `COMPLETED`».
- Esos identificadores son parte del contrato del comando **consigo mismo**: cambiar uno en
  una versión futura re-siembra por duplicado.
- THE SYSTEM SHALL apoyarse en que **cada avance de estado es idempotente por construcción** en vez
  de llevar su propia tabla de marcas: el caso de uso de avance elige candidatas por estado de
  origen y se traga el «no había transición» como «ya estaba ahí», y el de actualización de reserva
  no escribe ni registra nada cuando el valor ya está almacenado. Inventar estado propio para
  responder algo que el dataset ya responde sería un segundo sitio del que fiarse.
- WHERE la estancia `DIRECT` sigue en `PENDING`, THE SYSTEM SHALL confirmarla, y ése SHALL ser el
  **único** movimiento de la fase de avance que necesita una guarda explícita para no repetirse.
- THE SYSTEM SHALL comprobar las claves él mismo y no entregar al ingestor las filas que ya existen,
  y THE SYSTEM SHALL NOT delegar la idempotencia en `ReservationIngestor`: la suya es *actualizar*
  lo conocido, así que un segundo seed **al día siguiente** encontraría fechas distintas y
  modificaría las tres reservas.
- THE SYSTEM SHALL NOT re-anclar las fechas en una segunda ejecución. La composición
  pasada/activa/próxima describe una siembra **nueva**; un entorno sembrado hace dos semanas
  conserva las fechas de entonces y su reserva «activa» habrá terminado. Refrescar el dataset es
  tirar la base (`docker compose down -v`) y repetir `bootstrap` + `seed-demo`, documentado en
  `docs/seed-demo.md`.
- WHERE la reserva `DIRECT` se borra a mano y se vuelve a sembrar, THE SYSTEM SHALL crear una
  reserva nueva y un segundo «Pedro López», dejando huérfano al primero. Es la única entidad sin
  clave propia, a sabiendas: §27 no le da correo y el puerto de `guests` no busca por nombre. Queda
  fuera de la «segunda ejecución sobre la misma base» y en una base de demo el daño es una fila de
  más; lo fija un test para que no cambie en silencio.
- THE SYSTEM SHALL paginar esa búsqueda en lugar de suponer que cabe en una página: un entorno de
  demo usado acumula reservas reales junto a la sembrada.

### La plantilla de checklist del tenant

- WHEN el seed corre y el tenant no tiene ninguna plantilla, THE SYSTEM SHALL crear «Limpieza
  estándar» con los 18 items y las 6 fotos de PRD §7.10 invocando
  `CreateChecklistTemplateUseCase`, **sin `property_id`** — que es como el esquema escribe «todo el
  tenant» y por lo que esa columna es nullable.
- WHERE el tenant ya tiene al menos una plantilla, THE SYSTEM SHALL no crear otra, se llame como se
  llame: §27 pide una por tenant.
- THE SYSTEM SHALL escribir la forma que el código valida y no la que §7.10 dibuja:
  `{item_id, label, required}` y `{photo_type, label, required}`. **Divergencia declarada**: el PRD
  dibuja `label_es`/`label_en`/`order` y lo que `cleaning` implementó tiene **una** etiqueta y
  ordena por la posición en la lista, así que la etiqueta va en español —el `default_language` del
  tenant de §27— y el orden de §7.10 es el orden de la lista.
- THE SYSTEM SHALL poner `required: True` explícito en las 24 entradas: el parser lee un `required`
  ausente como `False` y exige un `bool` de verdad, `1` no vale.

### Contrato de consola y códigos de salida

| Código | Cuándo |
|---|---|
| 0 | Sembrado, o nada que hacer (segunda ejecución) |
| 1 | `SeedConfigurationError`: falta configuración, los dos correos `SEED_*` son el mismo, `tenants.timezone` no es una zona resoluble, o el tenant está en `S3` y falta bucket, región o credencial |
| 1 | `SeedPreconditionError`: el tenant de `BOOTSTRAP_TENANT_NAME` no existe; falta el owner o el manager; la limpieza de la demo no está asignada a la cuenta de `SEED_CLEANER_EMAIL`; el checkout aprovisionó una limpieza y no se encuentra; o la cuenta de `SEED_TECHNICIAN_EMAIL` no es un `TECHNICIAN` activo |
| 1 | `SeedConflictError`: un correo de las cuentas nuevas ya existe en otro tenant, o el clasificador no puso una incidencia donde el dataset declara |
| 2 | `SeedIngestError`: el ingest devolvió filas saltadas. Aquí **sí** se imprimen los motivos |
| 2 | Fallo inesperado: se imprime **sólo la clase** de la excepción |

- THE SYSTEM SHALL mantener esa tabla **sin introducir códigos nuevos**: la ampliación del dataset
  añadió refusals, no vocabulario.
- THE SYSTEM SHALL imprimir el recuento por entidad incluidas las tres nuevas —`cleaning_tasks`,
  `cleaning_photos` e `incidents`—, en una sola línea, con todos los tipos aunque valgan cero, y
  nada más.
- IF cualquier paso falla, THEN THE SYSTEM SHALL revertir la transacción entera, **incluidos los
  estados ya avanzados**.
- IF el fallo ocurre después de haber subido fotos, THEN THE SYSTEM SHALL enumerar en su salida de
  error las claves de los objetos que quedaron en el almacenamiento sin fila que los referencie,
  antes de propagar. **Enumerar no es limpiar**, y esa distinción es la que hace honesta la salida:
  el borrado compensatorio del caso de uso de subida está atado a **su propio** `commit`, que bajo
  la unidad de trabajo del llamante no ocurre nunca. Borrar los objetos huérfanos es una herramienta
  de operación propia y no existe.
- Enumerar esas claves **no choca** con la prohibición de exponer rutas internas: esa regla se acota
  a sí misma a la superficie de respuesta HTTP, y esto es la salida de error de un comando que
  ejecuta quien ya tiene las credenciales del almacén.

- THE SYSTEM SHALL comprobar las condiciones de código 1 **antes de la primera escritura**, y las
  de configuración además antes de abrir transacción.
- THE SYSTEM SHALL imprimir, en el catch-all, `type(exc).__name__` y nada más. Es una frontera de
  seguridad y no aseo: `StatementError.__str__` anexa `[SQL: INSERT INTO users ...] [parameters:
  (...)]`, y esos parámetros son las entradas de este comando — un hash bcrypt, un nombre, una
  dirección. Un `SEED_*_NAME` de más de 200 caracteres llega a ese sumidero por `DataError`.
- THE SYSTEM SHALL colocar la rama de `SeedIngestError` **por delante** del catch-all. Como hereda
  de `Exception`, un reordenamiento la desactivaría en silencio; lo fija un test.
- Es seguro imprimir los motivos del ingest por una razón **acotada**: todo `RowError.reason`
  alcanzable aquí es una frase fija, un nombre de campo o el `repr` de una constante literal de este
  módulo, y ningún valor `SEED_*` llega jamás al ingestor porque los dos DTO son literales del
  código. Si ese sumidero se ensancha, el mensaje vuelve al catch-all.
- THE SYSTEM SHALL no imprimir ninguna variable en un fallo de validación de configuración, y **no
  por cómo se llaman los campos**: `_load_settings` formatea `errors(include_input=False)`, así que
  ningún valor enviado llega al mensaje. No existe ningún patrón `*_password` en el módulo.
- `hide_parameters=True` en el engine cerraría el sumidero para toda la aplicación; queda fuera de
  alcance aquí y merece entrada de roadmap propia.

### Configuración

Las seis variables son **obligatorias y sin default en el árbol**, declaradas vacías en
`.env.example` junto al bloque `BOOTSTRAP_*`:

| Variable | Campo en `settings` |
|---|---|
| `SEED_CLEANER_NAME` | `seed_cleaner_name` |
| `SEED_CLEANER_EMAIL` | `seed_cleaner_email` |
| `SEED_CLEANER_PASSWORD` | `seed_cleaner_password` |
| `SEED_TECHNICIAN_NAME` | `seed_technician_name` |
| `SEED_TECHNICIAN_EMAIL` | `seed_technician_email` |
| `SEED_TECHNICIAN_PASSWORD` | `seed_technician_password` |

- Prefijo `SEED_` y no `BOOTSTRAP_`: son de otro comando, y el bloque `BOOTSTRAP_*` es exactamente
  el conjunto que `make bootstrap` exige.
- THE SYSTEM SHALL tomar `BOOTSTRAP_TENANT_NAME` como el nombre del tenant a completar; el tenant
  **no** es un argumento del comando.
- `ENCRYPTION_KEY` tiene que estar puesta porque `app.core.config` la exige al importar, aunque
  `CreatePropertyUseCase` sólo cifre si hay `wifi_password` y §27 no dé ninguna. `make up` la deja
  puesta desde `.env.example`, así que sólo muerde en un entorno montado a mano, y el fallo es en
  rojo.

**Dos condiciones más, que no son variables propias sino estado del tenant:**

- IF `tenants.timezone` no nombra una zona resoluble, THEN THE SYSTEM SHALL abortar con código 1
  nombrando la columna y **el valor rechazado**. Es la única refusal del comando que echa un valor,
  y lo hace porque nada de una zona horaria es sensible mientras que sin verla nadie sabe qué
  arreglar. El dataset se fecha sobre el día del calendario del tenant, así que esta columna es una
  entrada del comando aunque no viva en el entorno.
- IF el `storage_type` del tenant es `S3` y falta `S3_BUCKET`, `S3_REGION` o una credencial que la
  cadena del proveedor resuelva, THEN THE SYSTEM SHALL abortar con código 1 diciendo qué falta,
  **sin echar ningún valor**, y explicando que no hay respaldo a disco local.
- THE SYSTEM SHALL dejar `S3_ENDPOINT_URL` **fuera** de esa lista. Un endpoint vacío es la
  configuración **correcta** para AWS —es lo que hace que «apuntar a AWS» signifique no configurar
  nada—, así que exigirlo aquí rechazaría un despliegue que todos los demás caminos del sistema
  sirven sin problema. El almacén sobre el que corre `dev` sí lo necesita, y se entera por la vía
  ordinaria: su adaptador falla al escribir.
- THE SYSTEM SHALL preguntar por las credenciales **al paquete de almacenamiento**
  ([`file-storage.md`](file-storage.md)) y NEVER SHALL importar el SDK del proveedor desde el
  comando: sería un segundo punto de acoplamiento a un proveedor concreto, y además haría que la
  suite resolviera la cadena de credenciales de la máquina que la ejecuta.
- THE SYSTEM SHALL leer el `storage_type` del tenant con una consulta que **no inserte** su fila de
  configuración si no existe: es una comprobación previa, y una comprobación que escribe deja de
  serlo.

### Lo que este comando no hace

- **No abre en `reservations` la operación de check-in ni la de cierre que faltan.** Es la vía
  correcta y la que las apps de campo acabarán necesitando, pero es diseño de dominio nuevo y no
  cabe en un seed. Mientras no exista, este comando usa el sustituto que declara arriba.
- **No expone un `POST /incidents`.** `maintenance` explica por qué esa ruta no existe y qué la
  traerá; este comando escribe por casos de uso desde el CLI, no por HTTP.
- **No borra los objetos huérfanos que un fallo deje en el bucket**, sólo los enumera. Bajar la base
  (`docker compose down -v`) tampoco los toca.
- **No usa fotos con contenido representativo** de las viviendas reales: son imágenes sintéticas
  mínimas que la detección de tipo acepta. Sustituirlas es material de marketing, no de seed.
- **No toca la política de la máquina de estados ni las cadencias del scheduler.** Si el estado con
  el que abre la demo no gusta, la discusión es de [`timeline-state-machine.md`](timeline-state-machine.md).
- **No siembra aprobaciones de gasto, costes, pricing, statements ni reviews**: §27 no los describe.
  Las **conversaciones sí** se siembran desde el 2026-08-24, aunque §27 tampoco las describa: las pidió
  `demo-user` porque una demo con la bandeja vacía no enseña la mensajería con IA, que es media
  propuesta de valor del producto. `reviews` sigue fuera por un motivo distinto y más duro —
  `backend/app/reviews/` no tiene capa de aplicación ni router, así que sus filas no las leería ningún
  endpoint— y su casa es la entrada `revenue-reviews`.
- **No introduce un discriminador de entorno (`APP_ENV`)**, así que **no hay rechazo por entorno**.
  La protección son las variables obligatorias sin default y la ausencia de este comando de
  cualquier workflow de CD. Riesgo residual asumido: quien tenga shell en la VM de dev y rellene
  las variables puede sembrar allí; el entorno dev remoto es público por el túnel de Cloudflare y
  §27 publica una contraseña de demo en el PRD.
- **No toca `bootstrap.py`**, ni el esquema, ni ningún endpoint, ni `backend/openapi.json` (no hay
  endpoint nuevo), ni `locales/` (no hay UI).

### Deriva conocida con el fixture del mock

- `MockPMSAdapter` y el seed contienen dos versiones de las mismas reservas de §27, ya divergentes
  (`adults`). Son cosas distintas —fixture de ingest contra dataset de demo— y unificarlas ataría el
  segundo al primero, así que la duplicación se asume y se anota en `docs/seed-demo.md` para que
  quien lea las dos no crea que una está mal.

## Key files

- Comando: `backend/app/cli/seed_demo.py` — `build_plan`, `apply_plan`, `run`, `main`, las
  constantes del dataset de §27/§7.10 y los tres identificadores estables.
- Configuración: `backend/app/core/config.py` (los seis campos `seed_*`), `.env.example`.
- Orquestación: `Makefile`, target `seed-demo` → `python -m app.cli.seed_demo`.
- Vías canónicas que compone: `CreatePropertyUseCase`
  (`backend/app/properties/application/property_admin.py`), `CreateReservationUseCase` y
  `UpdateReservationUseCase` (`backend/app/reservations/application/use_cases.py`),
  `ReservationIngestor` (`backend/app/integrations/application/ingest.py`),
  `AdvancePropertyStatesUseCase` (`backend/app/properties/application/use_cases.py`),
  `CreateConversationUseCase` y `ProcessInboundGuestMessageUseCase` con `MockAIAdapter`
  (`backend/app/messaging/`), `IssueGuestAccessTokenUseCase` (portal de huésped),
  `CreateChecklistTemplateUseCase`, `ProvisionCleaningTaskUseCase`, `AcceptCleaningTaskUseCase`,
  `StartCleaningTaskUseCase`, `CompleteChecklistItemUseCase`, `UploadCleaningPhotoUseCase` y
  `CompleteCleaningTaskUseCase` (`backend/app/cleaning/application/use_cases.py`),
  `ReportIncidentUseCase`, `ClassifyIncidentUseCase` y `AssignIncidentUseCase`
  (`backend/app/maintenance/application/use_cases.py`), `User.create` +
  `SqlAlchemyUserRepository.add`, `Guest` + `SqlAlchemyGuestRepository.add`.
- Comprobación previa del almacén: `credentials_are_resolvable`
  (`backend/app/integrations/infrastructure/storage/s3.py`, reexportada por el paquete).
- Censo de sumideros de texto libre que lo vigila:
  `backend/tests/maintenance/test_free_text_sink_contract.py` — sigue a quien nombre
  `ReportIncidentUseCase` o `IncidentRepository`, precisamente porque este comando vive fuera de
  `maintenance/` y el guardián anterior no lo veía.
- Controles de auditoría que lo enumeran: `backend/tests/test_unscoped_reads.py`, que afirma
  que el conjunto de llamantes de `require_unmarked_session` es exactamente el declarado, y
  límite 2 del listener de `backend/app/core/db.py`.
- Tests: `backend/tests/cli/test_seed_demo.py` (directorio nuevo a propósito — el seed no pertenece
  a un dominio, atraviesa cinco). Los de la conversación y el enlace de portal viven ahí también;
  `backend/tests/cli/test_demo_reset.py` los ejercita como llamante.
- Segundo llamante de `apply_plan`: `backend/app/cli/demo_reset.py`
  (ver [`demo-tenant.md`](demo-tenant.md)).
- Documentación: `docs/seed-demo.md` (dataset, credenciales como *lo que pones en tu `.env`*,
  envejecimiento y cómo empezar de cero), `README.md` §«Entrar en la aplicación».
