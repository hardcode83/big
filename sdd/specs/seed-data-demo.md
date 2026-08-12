# Seed data de demo

## Purpose

`make seed-demo` llena un tenant **ya bootstrapeado** con el dataset de demo de PRD §27: las dos
viviendas reales, las dos cuentas operativas que faltan (`CLEANER` y `TECHNICIAN`), las tres
reservas —pasada, activa y próxima— y la plantilla de checklist de limpieza de PRD §7.10. Existe
para que un entorno recién levantado se pueda **recorrer** en vez de abrir un dashboard vacío, y
para que cada capability que llega sea demostrable sin escribir SQL a mano.

No crea el tenant: lo **completa**. `make bootstrap` sigue siendo lo único que da la primera
entrada a un entorno nuevo (ver spec `auth-tenancy`), y este comando presupone su resultado.

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
- THE SYSTEM SHALL validar toda su configuración en `build_plan()`, **antes** de abrir transacción,
  reportando de una vez todas las variables ausentes (mismo contrato que `bootstrap.build_plan`).
- THE SYSTEM SHALL validar también `BOOTSTRAP_TENANT_NAME` ahí, aunque no sea una de las seis
  variables propias: es lo que nombra al tenant a completar, así que vacía es *configuración que
  falta* y no *un tenant que no existe* — el mensaje de la precondición mandaría al lector a
  `make bootstrap` por una variable que nunca rellenó.
- THE SYSTEM SHALL no formar parte de `make up` ni de ningún workflow de CD, y THE SYSTEM SHALL NOT
  ser una migración de datos de Alembic — necesita valores que elige una persona.

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

### El actor de todo lo que el seed escribe es el `TENANT_OWNER`

- THE SYSTEM SHALL usar un único `actor_user_id`, el del `TENANT_OWNER` resuelto por rol, para las
  propiedades, las reservas, los `TimelineEvent` del ingest y las filas de `AuditLog`.
- No es una preferencia: las firmas de `CreatePropertyUseCase` y `CreateReservationUseCase`
  declaran `actor_user_id: uuid.UUID` no opcional, así que **un comando sin identidad no es
  expresable** por esa vía. Se elige el owner porque su existencia es un invariante del tenant
  mientras que un manager se puede dar de baja.
- Consecuencia asumida: en un entorno sembrado, `audit_logs` y `timeline_events` atribuyen al owner
  altas que hizo un comando. Es una propiedad del dataset de demo.

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
- THE SYSTEM SHALL no asignar `status` a ninguna de las tres. En la `DIRECT` es gratis
  (`CreateReservationCommand` no tiene el campo); en las OTA el DTO sí lo tiene y dejarlo `None` es
  deliberado — es el punto exacto donde un seed descuidado plantaría a mano el
  `CHECKED_IN_ESTIMATED` de §27 en vez de dejar que la máquina de estados y el scheduler de
  `celery-jobs` lleguen ahí.
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

### Idempotencia por identidad estable

- THE SYSTEM SHALL identificar cada entidad por una clave que **no depende del día**: las
  propiedades por `internal_code`; las cuentas por el correo normalizado; las reservas OTA por
  `external_pms_id` (`SEED-AIRBNB-1`, `SEED-BOOKING-1`); la `DIRECT` por `external_channel_id`
  (`SEED-DIRECT-1`), buscado paginando `ReservationRepository.list` filtrado por su propiedad; y la
  plantilla por «el tenant ya tiene al menos una».
- Esos tres identificadores son parte del contrato del comando **consigo mismo**: cambiar uno en
  una versión futura re-siembra por duplicado.
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
| 1 | `SeedConfigurationError`: falta configuración, o los dos correos `SEED_*` son el mismo |
| 1 | `SeedPreconditionError`: el tenant de `BOOTSTRAP_TENANT_NAME` no existe, o falta el owner o el manager |
| 1 | `SeedConflictError`: un correo de las cuentas nuevas ya existe en otro tenant |
| 2 | `SeedIngestError`: el ingest devolvió filas saltadas. Aquí **sí** se imprimen los motivos |
| 2 | Fallo inesperado: se imprime **sólo la clase** de la excepción |

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

### Lo que este comando no hace

- **No siembra las tres incidencias de PRD §27**: `maintenance` es quien define categoría,
  severidad, clasificación IA y asignación a técnico, y hoy el único escritor de `Incident` es la
  vía del portal del huésped, que deliberadamente no fija esos campos. Vuelve como ampliación del
  seed con `needs: maintenance`.
- **No lleva reservas a `CHECKED_IN_ESTIMATED` o `COMPLETED`, ni deja una limpieza completada con
  fotos**: son estados que se *alcanzan*, no valores que se asignan.
- **No introduce un discriminador de entorno (`APP_ENV`)**, así que **no hay rechazo por entorno**.
  La protección son las variables obligatorias sin default y la ausencia de este comando de
  cualquier workflow de CD. Riesgo residual asumido: quien tenga shell en la VM de dev y rellene
  las variables puede sembrar allí; el entorno dev remoto es público por el túnel de Cloudflare y
  §27 publica una contraseña de demo en el PRD.
- **No toca `bootstrap.py`**, ni el esquema, ni ningún endpoint, ni `backend/openapi.json` (no hay
  endpoint nuevo), ni `locales/` (no hay UI).
- **No siembra pricing, statements, reviews ni conversaciones**: §27 no los pide.

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
  (`backend/app/properties/application/property_admin.py`), `CreateReservationUseCase`
  (`backend/app/reservations/application/use_cases.py`), `ReservationIngestor`
  (`backend/app/integrations/application/ingest.py`), `CreateChecklistTemplateUseCase`
  (`backend/app/cleaning/application/use_cases.py`), `User.create` +
  `SqlAlchemyUserRepository.add`, `Guest` + `SqlAlchemyGuestRepository.add`.
- Controles de auditoría que lo enumeran: docstring de `find_by_email_globally`
  (`backend/app/auth/infrastructure/repositories.py`) y límite 2 del listener de
  `backend/app/core/db.py`.
- Tests: `backend/tests/cli/test_seed_demo.py` (directorio nuevo a propósito — el seed no pertenece
  a un dominio, atraviesa cinco).
- Documentación: `docs/seed-demo.md` (dataset, credenciales como *lo que pones en tu `.env`*,
  envejecimiento y cómo empezar de cero), `README.md` §«Entrar en la aplicación».
