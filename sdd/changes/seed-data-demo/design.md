# Design: seed-data-demo

## Context

`backend/app/cli/bootstrap.py` es hoy el único poblador: valida los `BOOTSTRAP_*` antes de abrir
transacción (`build_plan`), y luego escribe `TenantModel`, `TenantConfigModel` y dos `UserModel`
**directamente por SQLAlchemy** (`apply_plan`). No hay propiedades, reservas ni plantillas.

Las vías canónicas que este change necesita ya existen y están completas:
`CreatePropertyUseCase` (`backend/app/properties/application/property_admin.py:147`),
`CreateReservationUseCase` (`backend/app/reservations/application/use_cases.py:147`),
`ReservationIngestor` (`backend/app/integrations/application/ingest.py:102`, el núcleo compartido
por el import CSV y el sync del PMS) y `CreateChecklistTemplateUseCase`
(`backend/app/cleaning/application/use_cases.py:131`).

`backend/app/integrations/cli/pms_sync.py` es el modelo de cómo un comando compone casos de uso
fuera de FastAPI: importa `app.core.models_registry` por su efecto colateral, llama
`bind_session_to_tenant(session, tenant_id)` para que las lecturas ORM queden con scope de tenant,
inyecta repositorios `SqlAlchemy*` y un `SqlAlchemyUnitOfWork`, y separa `sync_with_session`
(trabajo sobre una sesión ajena, testeable) de `run` (abre la suya).

Tres asimetrías del código mandan sobre el diseño y aparecen abajo como decisiones: `CreateUserCommand`
no acepta contraseña y fuerza `must_change_password`; `CreateReservationUseCase` valida `guest_id`
pero no crea huéspedes; y `MockPMSAdapter` ya emite las dos reservas OTA de §27 —pero como fixture
de pruebas, con dos filas rotas a propósito y fechas derivadas de la ventana del sync.

## Decisions

### D1 — Un comando hermano de `bootstrap`, con su mismo esqueleto

**Chosen:** módulo nuevo `backend/app/cli/seed_demo.py` con el split `build_plan()` /
`apply_plan(session, ...)` / `run()` / `main()` de `bootstrap.py`, y target `seed-demo` en el
`Makefile` que ejecuta `$(COMPOSE) exec backend python -m app.cli.seed_demo`. El split no es
estética: es lo que permite que la suite ejercite `apply_plan` contra la base de tests sin abrir la
sesión del stack de desarrollo, exactamente como hacen `test_bootstrap.py` y
`test_reset_password_cli.py`.

Rejected: ampliar `bootstrap.py` — el proposal lo excluye, y mezclaría «lo mínimo para entrar» con
«el dataset de demo».
Rejected: migración de datos de Alembic — `bootstrap.py:5-7` ya argumenta por qué no.
Rejected: subcomando de `pms_sync` — no es un sync.

### D2 — La regla de escritura del seed, enunciada una vez

**Chosen:** el seed escribe **por el caso de uso cuando existe uno que hace lo que el seed
necesita**; cuando no existe, por la **entidad de dominio y su puerto**; **nunca** por un modelo
ORM. Es la regla que resuelve las dos tensiones que el proposal señala (R3 usuarios, R4.5
huéspedes) sin inventar excepciones caso a caso: lo que el seed no puede usar no es «el dominio»,
es la envoltura HTTP de un caso de uso concreto, y bajar un escalón —a la entidad y su puerto—
conserva todos los invariantes (validación de rol, guardas de cross-tenant, traducción de índices
únicos) que un `session.add(Model(...))` se salta.

Rejected: «todo por caso de uso» — imposible: no hay caso de uso que cree un usuario con contraseña
elegida ni uno que cree un huésped.
Rejected: «como bootstrap, modelos ORM» — convierte al seed en un segundo escritor con invariantes
duplicados, que es justo lo que la nota de roadmap da como motivo de la dependencia con
`properties-crud`.

### D3 — Los usuarios: `User.create` + el puerto, no `CreateUserUseCase`

**Chosen:** `User.create(..., must_change_password=False)` seguido de
`SqlAlchemyUserRepository.add(tenant_id, user)`, con el hash de `BcryptPasswordHasher` como en
`bootstrap`. La propia entidad lo autoriza por escrito: `must_change_password` **tiene default
`False`** y su docstring (`backend/app/auth/domain/entities.py:68`) dice que es así «so the
bootstrap path — whose passwords a person chooses — keeps today's behaviour». Lo que es
incompatible con R3.4 no es el dominio: es `CreateUserUseCase`, que genera la contraseña y por eso
marca el flag (design D9 de `user-management`). Por el puerto se conservan `GRANTABLE_ROLES`
(rechaza `SUPER_ADMIN`), `CrossTenantWriteError` y la traducción de `uq_users_lower_email` a
`EmailAlreadyExistsError`.

Rejected: añadir `password` a `CreateUserCommand` — debilita D9 de `user-management` en la vía HTTP
para servir a un comando, y el proposal excluye tocar módulos ajenos.
Rejected: componer `CreateUserUseCase` + `set_password_hash(..., temporary=False)` — dos
transacciones (el caso de uso ya hizo `commit`), una fila `USER_PASSWORD_RESET` que describe algo
que no ocurrió, y una ventana en la que la cuenta existe inutilizable.
Rejected: `session.add(UserModel(...))` como `bootstrap` — tercer escritor crudo de `users`, sin
ninguna de las tres guardas de arriba.

### D4 — Sólo se crean `CLEANER` y `TECHNICIAN`; el owner y el manager son los de `bootstrap`

**Chosen:** R3.1 («cuatro cuentas, una por rol») se cumple con **dos que ya existen y dos nuevas**.
El seed resuelve al `TENANT_OWNER` y al `PROPERTY_MANAGER` del tenant **por rol**
(`SqlAlchemyUserRepository.list` con `UserFilters(role=...)`), no por correo, y si falta alguno
aborta con la misma explicación que R1.3 («corre `make bootstrap` primero»). Las dos cuentas nuevas
salen de seis variables obligatorias sin default: `SEED_CLEANER_NAME/EMAIL/PASSWORD` y
`SEED_TECHNICIAN_NAME/EMAIL/PASSWORD`.

Por qué **por rol y no por los correos de §27**: los del owner y el manager los eligió el operador
en `BOOTSTRAP_OWNER_EMAIL`/`BOOTSTRAP_MANAGER_EMAIL`. Sembrar `owner@adamar.test` a ciegas crearía
una **quinta** cuenta y un **segundo** `TENANT_OWNER` en cuanto esos valores no coincidieran con los
del PRD. Consecuencia que hay que decir en voz alta y que la documentación de R6 recoge: los correos
de §27 para esas dos cuentas son **lo que pones en tu `.env`**, no algo que el comando imponga.

Rejected: seis variables más para re-declarar owner y manager — duplica configuración que ya existe
y abre la puerta a que las dos declaraciones discrepen.

### D5 — El actor de todo lo que el seed escribe es el `TENANT_OWNER`

**Chosen:** un único `actor_user_id`, el del `TENANT_OWNER` resuelto en D4, para
`CreatePropertyUseCase`, `CreateReservationUseCase`, los `TimelineEvent` del ingest y las filas de
`AuditLog` de D6. No es una preferencia: las firmas de los dos casos de uso declaran
`actor_user_id: uuid.UUID`, no opcional, así que **un comando sin identidad no es expresable** por
esa vía. Entre las cuentas disponibles se elige el owner porque su existencia es un invariante del
tenant (`assert_tenant_keeps_an_owner`, `backend/app/auth/domain/services.py`) mientras que un
manager se puede dar de baja.

Consecuencia asumida: en un entorno sembrado, `audit_logs` y `timeline_events` atribuyen al owner
altas que hizo un comando. Es una propiedad del dataset de demo, y la alternativa —actor nulo, como
`pms_sync` y `reset_password`— no cabe por la firma.

Rejected: crear un usuario técnico «SYSTEM» — `SUPER_ADMIN` no es grantable y cualquier otro rol
sería una quinta cuenta que nadie pidió, visible en la demo.

### D6 — El seed sí escribe el `AuditLog` del alta de las dos cuentas

**Chosen:** `AuditLogFactory.build(action=USER_CREATED, entity_type=ENTITY_USER, ...)` con el
`ChangeSet` que usa `CreateUserUseCase` —`email`, `role`, y `password` **redactado**— y el actor de
D5, escrito por `SqlAlchemyAuditLogRepository` dentro de la misma transacción. La regla 9 de
`steering/security.md` nombra «roles de User» y ésta es la única asignación de rol de la ejecución;
`reset_password.py` ya sienta el precedente de que un comando escribe su fila. Las altas de
propiedad y de reserva traen la suya de serie porque los casos de uso ya la escriben.

Rejected: no escribirla, como `bootstrap` — allí no hay ningún actor todavía (el tenant nace en esa
misma transacción); aquí sí lo hay, así que el argumento de `bootstrap` no se traslada.

### D7 — Las dos reservas OTA por `ReservationIngestor`, compuesto en el seed

**Chosen:** el seed construye dos `ReservationDTO` con los datos de §27 y los pasa a
`ReservationIngestor.ingest(...)` con un `resolve_property` que busca por **`internal_code`** —el
mismo resolver que `ImportReservationsFromCsvUseCase` (`use_cases.py:655`)— y `source="seed"`. El
ingestor no hace `commit`: la transacción la cierra el `SqlAlchemyUnitOfWork` del seed, igual que
hacen sus dos llamadores actuales. `resolve_property` es un parámetro precisamente porque «cómo se
resuelve la propiedad es la ÚNICA diferencia entre las dos rutas» (`ingest.py:8-9`), así que una
tercera puerta es la extensión que el módulo anticipa, no una violación.

Esto satisface R4.2 (`external_pms_id` asignado, canal OTA aceptado por `ReservationChannel.parse`)
y R4.5 (`_link_guest` registra a John Smith y María García con nombre y correo).

Rejected: `ImportReservationsFromCsvUseCase` — habría que sintetizar bytes CSV para volver a
parsearlos, acoplando el seed al formato del fichero, y el `TimelineEvent` diría «imported from
csv», que es falso.
Rejected: `SyncReservationsFromPmsUseCase` con `MockPMSAdapter`. Es la opción más tentadora, porque
`backend/app/integrations/infrastructure/mock_pms.py:58` **ya emite las dos reservas OTA de §27**, y
por eso conviene decir por qué no: (a) el mock deriva sus fechas de `since`, que el sync fija en
`now - window_days`, así que «activa hoy» se convierte en «activa hace 30 días» salvo que se le pase
una ventana de 0 —una trampa específica del mock—; (b) emite **dos filas rotas a propósito**, que el
seed reportaría como errores en cada ejecución; (c) sus filas resuelven por `PMS-REDES11`, un
identificador de fixture; y (d) sus datos ya divergen de §27 (`adults: 2` donde §27 dice 3). El
dataset de demo pasaría a depender de un fixture de pruebas y a moverse con él.

### D8 — La reserva `DIRECT` por su caso de uso, y su huésped por el puerto de `guests`

**Chosen:** `CreateReservationUseCase` para la reserva de Pedro López (R4.1), precedido de
`Guest(...)` + `SqlAlchemyGuestRepository.add(tenant_id, guest)` en la misma sesión, con la forma
exacta de `ReservationIngestor._link_guest` (`ingest.py:277`). R4.5 pide registrar al huésped «por
la misma vía que crea la reserva», y esa vía **no crea huéspedes**: `CreateReservationUseCase` sólo
comprueba que el `guest_id` existe. Es la misma asimetría de D3 y se resuelve igual — un escalón
por debajo del caso de uso, en la entidad y su puerto, nunca en el modelo.

El orden importa: `add` hace `flush`, y el `commit` del caso de uso cierra las dos escrituras; si la
reserva falla, el huésped se va con el rollback y no queda huérfano.

Rejected: pasar también la `DIRECT` por el ingest — le pondría un `external_pms_id`, que es mentira
(no viene de ningún PMS) y contradice R4.1.
Rejected: sembrarla sin huésped — incumple R4.5 y deja el detalle de reserva vacío justo en la
reserva que la demo usa para enseñar el pasado.

### D9 — Idempotencia por identidad estable; un segundo seed **no** re-ancla las fechas

**Chosen:** cada entidad tiene una clave de identidad que no depende del día:

| Entidad | Clave de idempotencia |
|---|---|
| Propiedades | `internal_code` (`PropertyRepository.find_by_internal_code`) |
| Usuarios | correo normalizado (`find_by_email_globally`, como `bootstrap`) |
| Reservas OTA | `external_pms_id` = `SEED-AIRBNB-1` / `SEED-BOOKING-1` (`find_by_external_pms_id`) |
| Reserva DIRECT | `external_channel_id` = `SEED-DIRECT-1`, buscado en `ReservationRepository.list` filtrado por la propiedad |
| Plantilla | «el tenant ya tiene al menos una» (`CleaningChecklistTemplateRepository.list`, `total > 0`) |

**El seed comprueba él mismo las claves y no entrega al ingestor las filas que ya existen.** No
delega la idempotencia en `ReservationIngestor`, porque la suya es *actualizar* lo conocido
(`_updatable_fields` + `update_details`): un segundo `seed-demo` **al día siguiente** encontraría
fechas distintas y **modificaría** las tres reservas, que es exactamente lo que R1.2 prohíbe.

De ahí la consecuencia que este diseño elige y que conviene leer despacio: **R1.2 manda sobre R4.3**.
R4.3 describe cómo queda una siembra *nueva* —corrida cualquier día produce la misma composición
pasada/activa/próxima—, no una re-siembra. Un entorno sembrado hace dos semanas y vuelto a sembrar
hoy conserva las fechas de entonces: la reserva «activa» habrá terminado. Quien quiera el dataset
fresco tira la base (`docker compose down -v`) y repite `bootstrap` + `seed-demo`; se documenta en
`docs/seed-demo.md`.

**El huésped de la reserva `DIRECT` es la única entidad sin clave, y se queda así a sabiendas**
(panel de QA de las secciones 4-6, 2026-08-12). Los otros dos huéspedes se identifican por correo
—`find_by_email`, el mismo criterio que usa `_link_guest`—, pero **§27 no le da correo a Pedro
López**, y R4.5 dice «nombre y correo *donde §27 lo da*»: inventarle uno para ganar una clave
sería deriva del dataset que el PRD fija, y el puerto de `guests` no ofrece búsqueda por nombre
(añadírsela sería justo el método de un solo llamante que este mismo D9 rechaza más abajo).

Consecuencia exacta, ni más ni menos: su creación va atada a la de la reserva, así que una segunda
siembra normal no lo duplica —la reserva ya está y el paso entero se salta—. Lo que sí lo duplica
es **borrar a mano la reserva `DIRECT` y volver a sembrar**: entonces nace una reserva nueva y un
segundo «Pedro López», quedando el primero huérfano. Es cirugía manual sobre la base, fuera del
«segunda ejecución sobre la misma base de datos» de R1.2, y en una base de demo el daño es una fila
de más. Queda fijado por `test_deleting_the_direct_stay_by_hand_and_reseeding_duplicates_its_guest`,
que existe para que este comportamiento no cambie en silencio, y anotado en `docs/seed-demo.md`
junto a la receta de empezar de cero.

**Enmienda del 2026-08-12, encontrada en el panel de `/sdd:review`: «hoy» es el día del
calendario del TENANT, no el de UTC.** Este diseño hablaba de fechas relativas «al día de
ejecución» sin decir en qué calendario se mide, y la implementación lo tomó de
`datetime.now(UTC).date()`. Son días distintos durante una parte de cada noche: entre las 00:00
y la 01:00 o las 02:00 de Madrid, UTC va todavía en el día anterior, así que las tres estancias
nacían un día antes del calendario local y la «activa» hacía checkout a las 11:00 de esa misma
mañana local en lugar del día siguiente. El comando resuelve ahora
`today = at.astimezone(ZoneInfo(tenant.timezone)).date()` y lo pasa como parámetro explícito a
los tres ayudantes que fechan (`_seed_reservations`, `_seed_direct_reservation`,
`_seed_ota_reservations`).

Tres precisiones que el criterio necesita y que conviene dejar escritas:

- **La zona del tenant y no la de la propiedad**, aunque quien resuelve el estado contextual
  use la de la propiedad (`ContextualStateResolver._zone`): para este dataset coinciden, porque
  las dos propiedades de §27 toman el default `Europe/Madrid`, y el tenant es quien nombra el
  entorno que R1.3 exige que exista.
- **Un solo ancla para las tres estancias.** Se calcula una vez y se pasa, en vez de
  recalcularse en cada ayudante, para que una ejecución lenta que cruce la medianoche no
  reparta el dataset entre dos días y rompa la composición de R4.3.
- **`now` sigue siendo UTC.** Sólo el *día del calendario* es local; todas las marcas de tiempo
  que se persisten (`created_at`, `AuditLog`, `TimelineEvent`) siguen en UTC.

No toca D9: `today` sólo se consume para construir filas que la comprobación de idempotencia ya
ha declarado ausentes, así que una segunda siembra lo calcula y lo descarta. Queda fijado por
`test_the_dates_are_anchored_to_the_tenants_day_and_not_to_utc`, y la lectura de
`tenants.timezone` está anotada en el límite 2 del listener de `app/core/db.py` junto a la del
`id`.

Rejected: re-anclar fechas en cada ejecución — viola R1.2 literalmente y haría del comando una
herramienta que muta datos existentes.
Rejected: anclar en UTC y documentarlo como limitación — R4.3 nombra offsets literales
(hoy−2 → hoy+1) sobre un dataset que existe para verse en pantalla; un día de desfase durante
dos horas cada noche no es una limitación, es la composición mal.
Rejected: identificar la `DIRECT` por propiedad + fechas, la letra de R4.6 — las fechas se mueven,
así que esa clave crea un duplicado cada día.
Rejected: añadir `find_by_external_channel_id` al puerto de `reservations` — un método de puerto con
un único llamante, y ese llamante un comando de demo.

### D10 — La plantilla se escribe con la forma que el código valida, no con la de PRD §7.10

**Chosen:** los 18 items y las 6 fotos de §7.10 con la forma que `parse_template_content`
(`backend/app/cleaning/domain/value_objects.py:216`) acepta y `items_as_json()` persiste:
`{item_id, label, required}` y `{photo_type, label, required}`. **Divergencia declarada**: §7.10
dibuja `label_es`/`label_en`/`order`; el esquema que `cleaning` implementó tiene **una** etiqueta y
ordena por la posición en la lista. El seed escribe la etiqueta en **español** (el
`default_language` del tenant de §27) y el orden de §7.10 como orden de la lista. Todos los items
van con `required: true` y las seis fotos también, que es lo que hace recorrible el cierre de
limpieza. Los 18 y las 6 caben de sobra (`MAX_ITEMS = 200`, `MAX_REQUIRED_PHOTOS = 50`) y los
identificadores de §7.10 pasan `KEY_PATTERN`.

Rejected: cambiar el esquema de plantillas para admitir dos idiomas — es un change de `cleaning`, no
del seed.

### D11 — Contrato de consola y códigos de salida

**Chosen:** mismo contrato que `bootstrap`. `build_plan()` valida **toda** la configuración antes de
abrir transacción y reporta **todas** las variables ausentes de una vez (R1.5); `main()` imprime
sólo recuentos por tipo de entidad y, como mucho, identificadores (R1.4).

| Código | Cuándo |
|---|---|
| 0 | Sembrado, o nada que hacer (segunda ejecución) |
| 1 | Falta configuración (R1.5) · **los dos correos `SEED_*` son el mismo** · el tenant de `BOOTSTRAP_TENANT_NAME` no existe (R1.3) · falta el owner o el manager (D4) · un correo de las cuentas nuevas ya existe en otro tenant (R3.6) |
| 2 | Fallo inesperado. Se imprime **sólo la clase** de la excepción — salvo la excepción acotada de abajo |
| 2 | `SeedIngestError`: el ingest de las reservas OTA devolvió filas saltadas. Aquí **sí** se imprimen los motivos |

Las condiciones de exit 1 se comprueban **antes de la primera escritura**, y las de configuración
(R1.5, incluida la de correos iguales) además antes de abrir transacción, para que «sin escribir
nada» sea una propiedad y no una esperanza.

**Por qué `SeedIngestError` puede imprimir su mensaje y el catch-all no** (panel de seguridad de la
sección 7). `ReservationIngestor.ingest` no levanta excepción por una fila mala: la cuenta en
`skipped`/`errors` y devuelve el informe. Eso es correcto para un CSV que subió una persona y falso
para un dataset que este módulo escribió él mismo, así que el seed falla en voz alta — y el motivo
es justo lo único que quien lo lea puede accionar. Es seguro imprimirlo, pero por una razón
**acotada y que conviene dejar escrita**: todo `RowError.reason` alcanzable aquí es una frase fija,
un nombre de campo, o el `repr` de una de las constantes literales de este módulo (`"REDES11"`,
`SEED-AIRBNB-1`…). Ningún valor `SEED_*` llega jamás al ingestor, porque los dos `ReservationDTO`
son literales del código. Si algún día ese sumidero se ensancha —una fila que venga de
configuración, un `str(error)` sobre una excepción que transporte entrada— esta fila deja de valer
y el mensaje vuelve al catch-all. La rama va **por delante** del `except Exception`, y como
`SeedIngestError` hereda de `Exception` un reordenamiento la desactivaría en silencio: lo fija
`test_an_ingest_failure_reaches_the_console_with_its_reasons`.

**Las dos últimas filas las añadió el panel de seguridad de las secciones 2-3**, y son la misma
historia contada en dos sitios. La enmienda de arriba subió la búsqueda de conflicto fuera del
bucle, a un diccionario indexado por correo; con `SEED_CLEANER_EMAIL` y `SEED_TECHNICIAN_EMAIL`
iguales esa clave se colapsa, las dos cuentas leen `None`, el bucle inserta dos veces y el segundo
`INSERT` muere dentro de `uq_users_lower_email`. Y ahí está el daño real: `StatementError.__str__`
de SQLAlchemy **anexa la sentencia con sus parámetros**, y uno de esos parámetros es el hash bcrypt
de una cuenta viva — exactamente lo que R1.4 prohíbe. De ahí las dos mitades: rechazar el correo
duplicado en `build_plan`, para que el flush no llegue a ocurrir, y un `except Exception` en
`main()` que imprime `type(exc).__name__` y nada más, para cerrar la clase entera y no sólo esta
instancia (un `SEED_*_NAME` de más de 200 caracteres llega al mismo sumidero por `DataError`).
`hide_parameters=True` en el engine de `app/core/db.py` cerraría el sumidero para toda la
aplicación; queda **fuera de alcance** aquí —es un cambio de comportamiento de todo el backend— y
merece entrada de roadmap propia.

R3.6 se comprueba con `find_by_email_globally` y el mismo razonamiento que `bootstrap.py:126-146`:
el índice único global rechazaría el `INSERT` de todos modos, así que la comprobación existe **por
el mensaje**, no por el invariante.

**Enmienda del 2026-08-12, encontrada al implementar la sección 3**: esa comprobación tiene que
correr **antes de `bind_session_to_tenant`**, no dentro del bucle que crea las cuentas. «No
scopeada» es una propiedad de la *sentencia*, no del método: en cuanto la sesión queda marcada, el
listener de `app/core/db.py` le añade la cláusula de tenant como a cualquier otra lectura ORM, así
que `find_by_email_globally` devuelve `None` para un correo de otro tenant y el seed acaba
insertando y recibiendo `EmailAlreadyExistsError` desde el índice — exactamente el fallo de base de
datos que R3.6 existe para sustituir por una explicación. El comando resuelve el tenant, hace las
dos búsquedas globales con la sesión aún sin marcar, y sólo entonces marca. D12 sigue en pie: lo
que cambia es qué ocurre *entre* resolver el tenant y marcar la sesión, y sigue sin haber ninguna
escritura ahí. Verificado por
`test_an_address_taken_by_another_tenant_is_refused`, que fallaba en rojo con la lectura dentro del
bucle.

### D12 — Scope de tenant en un comando

**Chosen:** `import app.core.models_registry` por su efecto colateral y `bind_session_to_tenant(session, tenant_id)`
inmediatamente después de abrir la sesión, antes de cualquier consulta —las dos cosas por el mismo
motivo que las documenta `pms_sync.py:31-41`: un comando tiene su propio grafo de imports y no pasa
por `get_authenticated_request`, que es quien normalmente marca la sesión. Ningún test unitario
detecta la ausencia de ninguna de las dos; la sección Verification tiene que ejecutar el comando de
verdad.

### D13 — Dónde se documenta (R6)

**Chosen:** `README.md` §«Entrar en la aplicación» gana el tercer paso (`make up` → `make bootstrap`
→ `make seed-demo`) y la precondición de R1.3; `.env.example` gana las seis variables vacías junto
al bloque `BOOTSTRAP_*`, con el comentario de «sin defaults»; y nace `docs/seed-demo.md` con el
dataset, las credenciales de §27 como *lo que pones en tu `.env`* (D4), la nota de envejecimiento de
D9 y cómo volver a empezar. `docs/` no tiene hoy página de arranque local —R6.3 dice «WHERE `docs/`
documenta el arranque local»— así que la capability estrena la suya, como pide
`steering/documentation.md`.

## Changes by area

| Area | Files | Change |
|---|---|---|
| CLI backend | `backend/app/cli/seed_demo.py` *(nuevo)* | Todo el comando: `build_plan`, `apply_plan`, `run`, `main`, y las constantes del dataset de §27/§7.10 |
| Config | `backend/app/core/config.py` | Seis campos nuevos con default `""` junto a los `bootstrap_*` (línea 298) |
| Orquestación | `Makefile` | Target `seed-demo` junto a `bootstrap`, con el mismo comentario de «no cuelga de `up`» |
| Entorno | `.env.example` | Bloque `SEED_*` vacío tras el bloque `BOOTSTRAP_*` |
| Docs | `README.md`, `docs/seed-demo.md` *(nuevo)* | R6.1 y R6.3 |
| Tests | `backend/tests/cli/test_seed_demo.py` *(nuevo)* | Ver abajo |
| Auth (sólo docstring) | `backend/app/auth/infrastructure/repositories.py` | La enumeración de llamantes de `find_by_email_globally`, y la condición de que la consulta corra sobre una sesión sin marcar |
| Core (sólo docstring) | `backend/app/core/db.py` | El seed en el límite 2 del listener: primer llamante que lee sin marcar y marca a media ejecución |

**Nada más se toca**, y las dos excepciones son docstrings, no comportamiento. No son alcance que
se cuele: los dos textos **son** controles de auditoría de la regla 1 de `steering/security.md` —
uno enumera los llamantes de la consulta sin scope, el otro enumera quién usa sesiones sin marcar—
y ambos dicen por escrito que quien añada un caso los actualice. Dejarlos intactos habría hecho
falsas dos listas que el resto del código cita. El primero, además, **no se amplió sino que se
sustituyó**: nombraba dos llamantes cuando ya había cinco, así que ahora remite al `grep` que
siempre fue la fuente exhaustiva. Ni `bootstrap.py`, ni los casos de uso, ni ningún puerto, ni el esquema, ni
`backend/openapi.json` (no hay endpoint nuevo, así que no aplica la regla de las dos mitades del
contrato de `steering/documentation.md`), ni `locales/` (no hay UI).

**Ubicación de los tests**: `backend/tests/cli/` es un directorio nuevo, y se desvía de la
convención «tests junto al dominio que cubren» (`steering/testing.md`) a propósito — el seed no
pertenece a un dominio, atraviesa cinco. `test_bootstrap.py` vive en `tests/auth/` porque bootstrap
sí es esencialmente de `auth`.

Cobertura mínima que las tareas deben producir: la validación de configuración incompleta (R1.5, sin
tocar la base), la ausencia de tenant (R1.3), la segunda ejecución (R1.2, contando filas antes y
después), el estado inicial `VACANT_READY` de las dos propiedades (R2.2), `must_change_password`
falso en las dos cuentas nuevas (R3.4), el conflicto de correo entre tenants (R3.6), el `status` con
que nace cada reserva (R4.4), el aislamiento de tenant de todo lo escrito (regla 1 de
`steering/security.md`, obligatorio por `steering/testing.md`), y que la salida no contiene ninguna
de las contraseñas (R1.4).

## Data & interfaces

**Esquema de base de datos: sin cambios.** Ni tablas, ni columnas, ni migración de Alembic.

**API: sin cambios.** No hay endpoint nuevo ni cambio de forma en ninguna respuesta.

**Variables de entorno nuevas** (las seis, obligatorias, sin default en el árbol — R3.2, regla 8 de
`steering/security.md`):

| Variable | Campo en `settings` |
|---|---|
| `SEED_CLEANER_NAME` | `seed_cleaner_name` |
| `SEED_CLEANER_EMAIL` | `seed_cleaner_email` |
| `SEED_CLEANER_PASSWORD` | `seed_cleaner_password` |
| `SEED_TECHNICIAN_NAME` | `seed_technician_name` |
| `SEED_TECHNICIAN_EMAIL` | `seed_technician_email` |
| `SEED_TECHNICIAN_PASSWORD` | `seed_technician_password` |

Prefijo `SEED_` y no `BOOTSTRAP_`: son de otro comando, y el bloque `BOOTSTRAP_*` es exactamente el
conjunto que `make bootstrap` exige. Un fallo de validación no imprime ninguna de las dos, y **no
por cómo se llaman**: `_load_settings` (`config.py:410-429`) formatea
`errors(include_input=False)`, así que ningún valor enviado llega al mensaje, se llame el campo
como se llame. No existe ningún patrón `*_password` en el módulo — creerlo haría que un futuro
`seed_*_secret` pareciera desprotegido, y que renombrar un campo pareciera un arreglo.

**Comando nuevo**: `make seed-demo` → `python -m app.cli.seed_demo`, sin argumentos. El tenant no es
un argumento (a diferencia de `pms_sync`) porque R1.3 lo fija en `BOOTSTRAP_TENANT_NAME`.

**Identificadores estables que el seed acuña** (D9): `SEED-AIRBNB-1`, `SEED-BOOKING-1` como
`external_pms_id`, y `SEED-DIRECT-1` como `external_channel_id`. Son parte del contrato del comando
consigo mismo: cambiarlos en una versión futura re-siembra por duplicado.

**Sin diagrama.** El flujo es una secuencia lineal de cinco pasos sobre una sola transacción; la
tabla de D9 y la de «Changes by area» dicen lo mismo que diría el dibujo (regla 11 compartida:
mirar una imagen cuesta ~140k de contexto).

## Risks & mitigations

- **El dataset envejece (D9).** Un entorno sembrado hace semanas enseña una reserva «activa» que ya
  terminó, y `seed-demo` no lo arregla. Mitigación: documentado en `docs/seed-demo.md` con la receta
  (`docker compose down -v` → `bootstrap` → `seed-demo`). Es una consecuencia elegida, no un
  descuido.
- **Contraseñas de demo en un entorno alcanzable.** El entorno dev remoto es público por el túnel de
  Cloudflare, y §27 publica `demo1234` en el PRD. La protección de este change es R3.2/R3.3
  —variables obligatorias, ningún default en el árbol— y la ausencia de este comando de cualquier
  workflow de CD. **No hay rechazo por entorno**: el proposal saca `APP_ENV` de alcance
  explícitamente. Riesgo residual asumido: quien tenga shell en la VM de dev y rellene las variables
  puede sembrar allí. Mitigación posible si se decide que no basta: entrada de roadmap para
  `APP_ENV`, fuera de este change.
- **`ENCRYPTION_KEY` tiene que estar puesta.** `CreatePropertyUseCase` llama `crypto.encrypt` sólo si
  hay `wifi_password`, y §27 no da ninguna, así que en la práctica no se ejerce; pero
  `app.core.config` la exige al importar. `make up` la deja puesta desde `.env.example`, así que sólo
  muerde en un entorno montado a mano; el fallo es en rojo y con mensaje, no silencioso.
- **Deriva con el fixture del mock.** `MockPMSAdapter` y el seed contienen ahora dos versiones de las
  mismas reservas de §27, ya divergentes hoy (`adults`). D7 asume la duplicación y no la arregla: son
  cosas distintas —fixture de ingest contra dataset de demo— y unificarlas ataría el segundo al
  primero. Se anota en `docs/seed-demo.md` para que quien lea las dos no crea que una está mal.
- **Ejecutar `seed-demo` antes que `bootstrap`.** Es el error de secuencia esperable; R1.3 lo
  convierte en exit 1 con un mensaje que nombra el comando que falta, comprobado antes de abrir
  transacción.

## Open questions

Ninguna abierta. Las tres que este diseño levantó las resolvió Jose en el gate del 2026-08-12, y
quedan cerradas aquí para que el registro no dependa de la conversación:

**OQ1 — ¿`Redes 11` nace con `pms_external_id = "PMS-REDES11"`, el identificador del
`MockPMSAdapter`? → NO.** El seed produce el dataset de §27 y nada más. Ponerlo habría hecho
demoable `make pms-sync` del tirón, al precio de que ese sync importara **dos reservas más** —las
del mock, con fechas desplazadas por la ventana— sobre las tres del seed y reportara los dos errores
que el mock emite a propósito. Quien quiera demostrar el sync pone el identificador a mano por
`PATCH`.

**OQ2 — ¿Se acepta que una segunda ejecución no re-ancle las fechas (D9)? → SÍ.** R1.2 manda sobre
R4.3, que describe una siembra nueva. Refrescar el dataset es tirar la base (`docker compose down
-v`) y repetir `bootstrap` + `seed-demo`. Si algún día hace falta refrescarlo in situ, será una
entrada de roadmap con verbo propio (`make reseed-demo`), nunca un efecto lateral de este comando.

**OQ3 — ¿Escribe el seed las filas de `AuditLog` del alta de las dos cuentas (D6)? → SÍ.** La
atribución imprecisa al owner (D5) ya es inevitable en propiedades y reservas —sus casos de uso
escriben la fila de todos modos—, así que no escribirlas sólo conseguiría dejar sin rastro la única
asignación de rol de la ejecución. D6 queda como está redactada.
