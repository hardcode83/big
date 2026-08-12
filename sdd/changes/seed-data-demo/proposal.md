# Proposal: seed-data-demo

## Why

Hoy no se puede recorrer el producto. `make bootstrap` (`backend/app/cli/bootstrap.py`) crea **un tenant, su `TenantConfig` y exactamente dos usuarios** (`TENANT_OWNER` y `PROPERTY_MANAGER`) — **ninguna propiedad, ninguna reserva, ninguna plantilla de limpieza**. Un entorno recién levantado abre el dashboard vacío, así que cada capability que llega se demuestra escribiendo SQL a mano o creando datos por la API uno a uno, y nadie puede ver el producto funcionando de punta a punta.

PRD §27 («Seed data») especifica exactamente el dataset que hace falta: tenant «Adamar Inmuebles», las dos propiedades reales (REDES11, PAJARITOS8), cuatro usuarios cubriendo los cuatro roles, tres reservas en distintos momentos, tres incidencias y la plantilla de checklist. Esta entrada se **separó de `hardening-release` el 2026-08-07** precisamente porque allí iba detrás de todo (suite E2E, docker, DoD §28), cuando en realidad es lo que hace demostrable cada capability *a medida que llega*.

Fuentes: PRD §27 (dataset), PRD §7.10 (plantilla de checklist por defecto), nota de roadmap `sdd/roadmap/seed-data-demo.md` (el porqué de la dependencia y la obligación de seguridad).

## What changes

Un comando nuevo — `make seed-demo`, sobre un módulo CLI hermano de `bootstrap.py` — que **completa** el tenant que `bootstrap` ya creó con las dos propiedades de §27, los dos usuarios operativos que faltan (`CLEANER`, `TECHNICIAN`), las tres reservas y la plantilla de checklist del tenant. Escribe **siempre a través de las vías canónicas** de cada dominio (`CreatePropertyUseCase`, `CreateReservationUseCase`, la vía de import para canales OTA, `CreateChecklistTemplateUseCase`) en proceso, como un cliente más: no inserta modelos por su cuenta y por tanto no se convierte en un segundo escritor con invariantes duplicados. Es idempotente, no toca `bootstrap.py`, y las contraseñas de los cuatro usuarios salen de variables de entorno obligatorias sin default en el árbol.

Lo que §27 pide y **no** entra aquí (ver *Out of scope*): las incidencias, y los estados que no se asignan sino que se alcanzan.

## Requirements

### R1 — Un comando de seed reproducible

**Como** operador de un entorno recién levantado, **quiero** un comando único que lo llene con el dataset de demo, **para** poder recorrer el producto sin escribir SQL a mano.

Criterios de aceptación:

1. WHEN el operador ejecuta `make seed-demo` sobre una base de datos migrada cuyo tenant ya existe, THE SYSTEM SHALL crear el dataset en alcance (propiedades de R2, usuarios de R3, reservas de R4, plantilla de R5) e imprimir un recuento por tipo de entidad creada.
2. WHEN el comando se ejecuta una segunda vez sobre la misma base de datos, THE SYSTEM SHALL no crear ninguna fila nueva, no modificar ninguna existente, y terminar con código de salida 0.
3. IF el tenant nombrado por `BOOTSTRAP_TENANT_NAME` no existe en la base de datos, THEN THE SYSTEM SHALL abortar con código de salida distinto de 0, indicando que `make bootstrap` debe correr primero, **sin escribir nada**.
4. THE SYSTEM SHALL imprimir únicamente recuentos e identificadores — nunca contraseñas, hashes ni tokens.
5. THE SYSTEM SHALL validar toda su configuración **antes** de abrir cualquier transacción, reportando de una vez todas las variables que falten (mismo contrato que `bootstrap.build_plan`).

### R2 — Las dos propiedades por su vía de escritura canónica

**Como** propietaria, **quiero** ver REDES11 y PAJARITOS8 en el dashboard tras sembrar, **para** que el producto muestre viviendas reales y no un estado vacío.

Criterios de aceptación:

1. WHEN el seed corre, THE SYSTEM SHALL crear las dos propiedades de PRD §27 (`Redes 11`/`REDES11` y `Pajaritos 8`/`PAJARITOS8`) con sus valores de dirección, `max_guests`, `bedrooms`, `bathrooms` y horas por defecto, invocando `CreatePropertyUseCase`.
2. THE SYSTEM SHALL no pasar ni escribir `current_operational_state`, de modo que ambas propiedades nazcan en `VACANT_READY` por el camino que `PropertyStateMachine` gobierna.
3. WHERE el tenant ya contiene una propiedad con ese `internal_code`, THE SYSTEM SHALL dejarla intacta y no crear una segunda.
4. THE SYSTEM SHALL no escribir directamente en la tabla `properties`: toda creación pasa por el caso de uso.

### R3 — Los cuatro usuarios, con credenciales conocidas y utilizables

**Como** persona que hace la demo, **quiero** poder entrar como propietaria, manager, limpiadora y técnico con credenciales que conozco, **para** recorrer las cuatro vistas del producto sin trámites intermedios.

Criterios de aceptación:

1. WHEN el seed corre, THE SYSTEM SHALL asegurar la existencia de cuatro cuentas en el tenant, una por cada rol: `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`.

   > **Enmienda del 2026-08-12** (panel de `/sdd:review`). Este criterio decía «cuatro cuentas en el tenant **con los correos de PRD §27**», y el diseño lo cumplió a sabiendas de otra manera: el owner y el manager se resuelven **por rol** (D4), porque sus direcciones las eligió quien bootstrapeó el entorno en `BOOTSTRAP_OWNER_EMAIL`/`BOOTSTRAP_MANAGER_EMAIL`, y sembrar `owner@adamar.test` a ciegas crearía una quinta cuenta y un segundo `TENANT_OWNER` en cuanto esos valores no coincidieran con los del PRD. Las otras dos salen de `SEED_CLEANER_EMAIL`/`SEED_TECHNICIAN_EMAIL`. Lo que este criterio pide, y sigue pidiendo, son **los cuatro roles presentes y operativos**: los correos de §27 son un ejemplo de configuración y no parte del contrato — que es exactamente lo que `README.md` y `docs/seed-demo.md` dicen en voz alta. La letra anterior describía algo que el código no hacía ni debía hacer, igual que pasó con R4.5.
2. THE SYSTEM SHALL tomar la contraseña de cada cuenta de una variable de entorno **obligatoria**, y el árbol de código SHALL NOT contener ningún valor por defecto para ellas — `.env.example` las declara vacías, igual que las `BOOTSTRAP_*_PASSWORD` existentes.
3. IF falta alguna de esas variables, THEN THE SYSTEM SHALL abortar antes de abrir transacción listando todas las ausentes (R1.5), en lugar de sembrar una contraseña conocida.
4. WHEN una de las cuatro cuentas queda creada, THE SYSTEM SHALL dejarla en condiciones de operar inmediatamente — sin cambio de contraseña forzado (`must_change_password` en falso) — porque una demo que exige rotar cuatro contraseñas antes del primer clic no es una demo.
5. WHERE una cuenta con ese correo ya existe en el tenant, THE SYSTEM SHALL dejarla intacta, incluida su contraseña actual.
6. IF un correo de §27 ya existe **en otro tenant** de la instalación, THEN THE SYSTEM SHALL abortar explicando el conflicto, en lugar de dejar que el índice único global falle con un error de base de datos.

> **Tensión que el diseño tiene que resolver, no ocultar**: `CreateUserCommand` (`backend/app/auth/application/user_admin.py`) deliberadamente **no acepta contraseña** — la genera y marca `must_change_password` (design D9 de `user-management`), y `set_password_hash(..., temporary=True)` es lo que usa también el rescate de `app/cli/reset_password.py`. Es decir: la vía canónica de creación de usuarios es incompatible con R3.4 tal cual. La única vía existente que produce cuentas con contraseña conocida y operativas es la de `bootstrap.py`, que escribe `UserModel`. `/sdd:design` debe elegir entre extender esa vía de seed ya establecida o componer creación canónica + fijación posterior de contraseña, y decir por qué.

### R4 — Las tres reservas, cada una por la vía que su canal permite

**Como** manager, **quiero** encontrar reservas pasada, activa y próxima tras sembrar, **para** que el timeline y el dashboard tengan algo que contar.

Criterios de aceptación:

1. WHEN el seed corre, THE SYSTEM SHALL crear la reserva `DIRECT` de §27 (Pedro López, hoy−10 → hoy−7) invocando `CreateReservationUseCase`.
2. WHEN el seed corre, THE SYSTEM SHALL crear las reservas de canal `AIRBNB` y `BOOKING` de §27 por la vía de importación, que asigna `external_pms_id` — porque `CreateReservationCommand.__post_init__` **rechaza** todo canal que no sea `MANUAL` o `DIRECT`, y esa regla es la que evita reimportar la misma estancia como fila nueva.
3. THE SYSTEM SHALL fechar las tres reservas relativas al día de ejecución conforme a §27 (hoy−2 → hoy+1; hoy+3 → hoy+7; hoy−10 → hoy−7), de modo que un seed corrido cualquier día produzca la misma composición pasada/activa/próxima.
4. THE SYSTEM SHALL no asignar `status` a mano en ninguna de las tres: cada reserva nace en el estado por defecto de su agregado y avanza, si avanza, por la máquina de estados y el scheduler de `celery-jobs`.
5. THE SYSTEM SHALL registrar los tres huéspedes de §27 (nombre y correo donde §27 lo da) por la vía canónica de su dominio, **nunca escribiendo el modelo ORM de `guests`**.

   > **Enmienda del 2026-08-12** (panel de seguridad de las secciones 4-6). Este criterio decía «por la misma vía que crea la reserva, sin escribir `guests` por su cuenta», y para la reserva `DIRECT` eso es **inexpresable**: `CreateReservationUseCase` sólo comprueba que el `guest_id` exista, no crea huéspedes. D8 ya lo resolvió bajando un escalón —`Guest(...)` + `SqlAlchemyGuestRepository.add`, la misma forma que usa `ReservationIngestor._link_guest`— pero la letra del criterio seguía describiendo algo que el código no hacía ni podía hacer. Lo que la redacción quería prohibir, y sigue prohibiendo, es un `session.add(GuestModel(...))`: por el puerto se conservan el scope de tenant y `CrossTenantWriteError`. Los dos huéspedes de OTA sí entran por `_link_guest`, dentro del ingestor.
6. WHERE una reserva sembrada por este comando ya existe —identificada por el identificador estable que él mismo acuña— THE SYSTEM SHALL no crear un duplicado (R1.2).

   > **Enmienda del 2026-08-12** (panel de `/sdd:review`). Decía «para esa propiedad y esas fechas», y esa clave es inservible precisamente aquí: las fechas son relativas al día de ejecución (R4.3), así que identificar por propiedad+fechas crearía un duplicado nuevo **cada día**, que es lo contrario de lo que el criterio quiere. D9 lo resolvió con identidad estable (`SEED-DIRECT-1`, `SEED-AIRBNB-1`, `SEED-BOOKING-1`) y dejó la letra fuera de lo alcanzable. Consecuencia aceptada, ahora explícita en vez de tácita: una estancia creada **a mano** en la misma propiedad y con las mismas fechas, sin `external_channel_id`, no impide que el seed cree la suya. Eso es cirugía manual sobre la base, fuera del «segunda ejecución sobre la misma base de datos» que R1.2 gobierna, y en una base de demo el daño es una fila de más.

### R5 — La plantilla de checklist del tenant

**Como** limpiadora, **quiero** que la tarea de limpieza que me llegue traiga checklist, **para** que el módulo de limpieza sea recorrible tras sembrar.

Criterios de aceptación:

1. WHEN el seed corre y el tenant no tiene ninguna plantilla de checklist, THE SYSTEM SHALL crear la plantilla por defecto de PRD §7.10 invocando `CreateChecklistTemplateUseCase`, aplicable a ambas propiedades.
2. WHERE el tenant ya tiene al menos una plantilla, THE SYSTEM SHALL no crear otra.

### R6 — El camino de demo, documentado donde se busca

**Como** desarrollador nuevo en el repo, **quiero** que el README me diga la secuencia completa, **para** no descubrir por prueba y error que `seed-demo` necesita `bootstrap` antes.

Criterios de aceptación:

1. WHEN un desarrollador lee el README de la raíz, THE SYSTEM SHALL documentar la secuencia `make up` → `make bootstrap` → `make seed-demo`, y que el seed exige un tenant ya creado (R1.3).
2. THE SYSTEM SHALL declarar en `.env.example` todas las variables nuevas que el seed requiere, vacías y con un comentario que diga que no hay defaults, junto al bloque `BOOTSTRAP_*` existente.
3. WHERE `docs/` documenta el arranque local, THE SYSTEM SHALL reflejar allí el mismo camino, conforme a `steering/documentation.md`.

## Out of scope

- **Las tres incidencias de PRD §27.** `maintenance` está abierto en el roadmap y es quien define categoría, severidad, clasificación IA y asignación a técnico; hoy el único escritor de `Incident` es la vía del portal del huésped, que deliberadamente **no** fija esos campos (`backend/app/maintenance/application/use_cases.py`, R5.4 de `guest-portal-api`). Sembrarlas ahora significaría duplicar invariantes que `maintenance` va a definir después. → Debe volver como entrada de roadmap que amplía el seed, con `needs: maintenance`.
- **Llevar reservas a `CHECKED_IN_ESTIMATED` o `COMPLETED`, y dejar una limpieza completada con fotos.** Son estados que se *alcanzan* por la máquina de estados, el scheduler de `celery-jobs` y el flujo de cierre de limpieza — no valores que se asignan. R4.4 lo excluye explícitamente. → Misma ampliación futura del seed.
- **Introducir un discriminador de entorno (`APP_ENV`) en `backend/app/core/config.py`.** Hoy no existe, y añadirlo es alcance que afecta a todo el backend. La protección de credenciales de este change es R3.2/R3.3 (variables obligatorias, sin defaults), no un rechazo por entorno.
- **Sembrar el entorno dev remoto.** Este comando es para entornos que el operador controla; nada aquí lo ejecuta en dev ni en CD.
- **Modificar el comportamiento de `bootstrap.py`.** El seed lo *presupone* y lo complementa; si hiciera falta cambiarlo, es otro change.
- **Datos de pricing, statements, reviews o conversaciones.** §27 no los pide, y sus capabilities no existen todavía.
- **Poblar `.env` del desarrollador con los valores de §27.** `.env.example` los declara vacíos; quien quiera las credenciales de demo las escribe en su `.env`.

## Affected specs

- `sdd/specs/seed-data-demo.md` — *(no existe aún — se creará al archivar)*
- `sdd/specs/local-environment.md` — documenta hoy `make bootstrap` y el arranque local; añade el nuevo target y su precondición.
- `sdd/specs/auth-tenancy.md` — menciona las variables `BOOTSTRAP_*`; hay que reflejar las nuevas y que las cuatro cuentas de demo nacen operativas.
- `sdd/specs/properties-crud.md`, `sdd/specs/reservations.md`, `sdd/specs/cleaning.md` — se revisan por si el seed añade consumidores en proceso de sus casos de uso que las specs deban nombrar; **no** se espera cambiar su comportamiento.

## ASSUMPTION

- El tenant, su `TenantConfig`, `country`/`timezone`/`default_language` y los umbrales de §27 **ya los produce `make bootstrap`**: los defaults de `TenantModel` y `TenantConfigModel` (`backend/app/tenants/infrastructure/models.py`) coinciden literalmente con los valores de PRD §27, y el nombre «Adamar Inmuebles» y el correo de facturación entran por `BOOTSTRAP_TENANT_NAME`/`BOOTSTRAP_TENANT_BILLING_EMAIL`. Por eso este change no crea tenant ni config, y R1.3 exige que ya existan.
