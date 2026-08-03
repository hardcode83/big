# Proposal: channex-staging-adapter

## Why

`MockPMSAdapter` es hoy la **única** implementación de `PMSAdapter`
(`backend/app/integrations/domain/ports.py`), y `pms_sync` lo construye a pelo
(`backend/app/integrations/cli/pms_sync.py:74`). Todo lo que el backend sabe de un PMS
lo sabe de un mock que escribimos nosotros: `ReservationIngestor`, la idempotencia por
`(tenant_id, external_pms_id)`, la persistencia de `TimelineEvent` y el CLI de sync
están verificados contra datos que nunca han pasado por una API real. Eso no es una
suite débil — es que **el mock no puede sorprendernos**, y las sorpresas de un PMS real
(campos ausentes, paginación, orden de eventos, límites) son exactamente lo que
`pms-beds24-adapter` tendrá que absorber.

Channex ofrece `staging.channex.io` **gratis, self-serve, sin tarjeta y sin caducidad**,
y es el único proveedor evaluado que da acceso al **entorno de test de Booking.com** con
propiedades de test prestadas — no existe sandbox de OTA en ningún otro
([ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md), decisión 2:
*"se abrirá en paralelo desde ya"*). Es, literalmente, el único sitio donde hoy podemos
validar nuestro backend contra un PMS real sin gastar reloj ni tocar los dos anuncios
que están vendiendo.

**Relación con la decisión de proveedor, que no cambia.** ADR 0006 elige **Beds24** para
el MVP y sitúa Channex en fase SaaS (25–50 uds); `steering/product.md` lo recoge así.
Este change **no reabre esa decisión**: el `ChannexAdapter` que produce es un adapter de
**dev/staging**, una herramienta de validación, no el proveedor de producción. El
principio 3 de `product.md` —*"MVP de calidad producción end-to-end con adapters mock
donde falten credenciales"*— apunta en esta dirección: aquí las credenciales **no
faltan**, así que un adapter real es estrictamente mejor que el mock.

**Por qué antes que Beds24, y es una cuestión de relojes.** El trial de Beds24 son 14
días que empiezan a contar al registrarse. Channex staging no caduca. Aprender el modelo
de datos de un PMS, el mapeo a `ReservationDTO` y la mecánica de una reserva de OTA aquí
significa que los 14 días de Beds24 se gastan íntegros en **medir** (`X-RequestCost`,
latencia de webhooks) en vez de en aprender. Es la razón por la que esta entrada se
separa de `pms-beds24-spike`, que se queda solo con la pata Beds24.

Fuente: entrada `pms-beds24-spike` de `sdd/roadmap.md` (pata Channex, ahora entrada
propia) y ADR 0006 decisión 2.

## What changes

Después de este change existirá una cuenta de Channex staging operativa y documentada,
un `ChannexAdapter` que implementa el puerto `PMSAdapter` real contra su API, una
selección de proveedor por variable de entorno para `pms_sync` (con `mock` por defecto,
declarada como stopgap hasta la `PMSAdapterFactory` de ADR 0006), fixtures de payloads
reales anonimizados con el script que los captura, y `docs/channex-staging.md` con el
runbook operativo, la evidencia de una reserva end-to-end real llegada desde el entorno
de test de Booking.com hasta nuestra base de datos, y los límites de la API medidos como
entrada de diseño de `pms-beds24-adapter`.

**Las credenciales viven en el entorno, no en base de datos.** Es la decisión de alcance
que mantiene este change pequeño y es la que la regla 3 de `steering/security.md`
contempla de forma explícita: exige Fernet para *"toda credencial de proveedor externo
**que no viva en el entorno**"*. Al no persistir ninguna credencial, las cinco
obligaciones de ADR 0006 decisión 7 (Fernet, test de aislamiento propio, contrato de solo
escritura, `AuditLog` de lectura/rotación, marcado de sesión) siguen siendo de
`pms-beds24-adapter`, que es donde nacen las columnas.

## Requirements

### R1 — Entorno de staging operativo, con el aviso de canal como regla dura

**As a** desarrollador del backend, **I want** una cuenta de Channex staging con
propiedades de test y su alta documentada, **so that** pueda ejercitar el sistema contra
un PMS real sin poner en riesgo los dos anuncios que están vendiendo.

Acceptance criteria:

1. WHEN se complete el alta en `staging.channex.io`, THE SYSTEM SHALL documentar en
   `docs/channex-staging.md` los pasos reproducibles (grupo, propiedad de test,
   generación de la API key, endpoints base) **sin incluir ningún valor de credencial**.
2. WHERE el runbook describa la conexión de canales, THE SYSTEM SHALL declarar de forma
   explícita que solo se usan las propiedades de test prestadas por Channex y que
   conectar la cuenta real de Airbnb está **prohibido**, indicando el motivo: Airbnb
   admite un único channel manager por cuenta, Channex falla en duro si ya hay otro, y
   desconectar el actual abriría una ventana de corte sobre anuncios activos.
3. IF algún paso del alta no se puede reproducir sin intervención de Channex (p. ej. el
   préstamo de propiedades de test), THEN THE SYSTEM SHALL marcarlo en el runbook como
   `EXTERNAL_DEPENDENCY`, con el canal de contacto usado y la fecha.

### R2 — `ChannexAdapter`: una implementación real del puerto `PMSAdapter`

**As a** desarrollador del backend, **I want** una implementación de `PMSAdapter` contra
la API de Channex staging, **so that** los casos de uso ya escritos se validen contra
datos que vienen de un PMS de verdad y no de un mock que escribimos nosotros.

Acceptance criteria:

1. WHEN se invoque `list_reservations(since, property_external_id=None)` sobre el
   `ChannexAdapter` con credenciales de staging válidas, THE SYSTEM SHALL devolver
   `list[ReservationDTO]` con la misma forma que devuelve `MockPMSAdapter`, incluyendo
   `raw_payload` con el cuerpo del proveedor sin tocar.
2. WHEN se invoque `get_reservation(external_id)` con un id que Channex no conoce, THE
   SYSTEM SHALL devolver `None` en vez de lanzar, igual que el mock — la
   sustituibilidad de Liskov que exige `steering/backend-architecture.md` es un
   requisito del puerto, no una cortesía.
3. IF la API de Channex responde con error de transporte, de autenticación o de límite
   de tasa, THEN THE SYSTEM SHALL lanzar la misma clase de error que el resto del sistema
   ya espera de este puerto, y THE SYSTEM SHALL no incluir la API key en el mensaje de
   error ni en ningún log.
4. WHERE el adapter mapee campos de Channex a `ReservationDTO`, THE SYSTEM SHALL dejar
   documentado en el código todo campo de PRD §16 que Channex no proporcione,
   asignándole `None` en vez de un valor inventado.
5. THE SYSTEM SHALL cubrir el mapeo con tests que se ejecuten **sin red**, alimentados
   por los fixtures de R4, de modo que la suite de CI no dependa de la cuenta de staging.

> **Amendment (2026-08-03, tras capturar los payloads reales de la tarea 2.3)**: los tres
> criterios siguientes no estaban, y salen de medir el proveedor en vez de leer su
> documentación. Detalle y evidencia en `design.md` §"D7 bis".

6. WHERE el proveedor entregue un valor de comisión que **no distingue** "cero" de "no
   informado" —Channex devuelve siempre un string y normaliza el ausente a `"0.00"`—, THE
   SYSTEM SHALL resolver la ambigüedad **en el adapter**, respetando el valor solo cuando
   la OTA es de las que ese proveedor informa y devolviendo `None` en cualquier otro caso,
   incluida una OTA desconocida.
7. WHEN el proveedor use un vocabulario de estado propio, THE SYSTEM SHALL traducirlo en
   el adapter al vocabulario canónico de `ReservationStatus`, y IF el estado recibido no
   está en esa traducción, THEN THE SYSTEM SHALL propagarlo sin traducir para que la
   validación de dominio lo rechace y la fila se reporte — nunca adivinar un estado, que
   es lo que conduce la `PropertyStateMachine`.
8. WHEN el adapter construya un filtro temporal contra el proveedor, THE SYSTEM SHALL
   enviarlo en UTC **sin offset**, porque Channex ignora el offset recibido y compara el
   reloj de pared literal — un ISO tz-aware desde Madrid en verano deja fuera las reservas
   de las dos últimas horas sin error alguno.

### R3 — Selección de proveedor en el comando, declarada como stopgap

> **Amendment (2026-08-03, gate de `/sdd:design`)**: R3.1 y R3.2 hablaban de una
> *variable de entorno*. La decisión D3 del design las pasa a un **flag del comando**
> `pms_sync`, para no resucitar el `PMS_PROVIDER` global que ADR 0006 retiró en favor de
> resolución por propiedad. El resto de R3 no cambia.

**As a** desarrollador, **I want** poder elegir entre el mock y Channex sin editar
código, **so that** pueda alternar entre la suite offline y la validación contra
staging, sin que el cambio se convierta en la resolución por propiedad que ADR 0006
asigna a otro change.

Acceptance criteria:

1. WHEN se invoque `pms_sync` sin `--provider`, THE SYSTEM SHALL usar `MockPMSAdapter`,
   de forma que el comportamiento actual del comando, de la suite y del arranque local no
   cambie en absoluto.
2. WHEN `--provider channex` seleccione Channex y falte la API key en el entorno, THE
   SYSTEM SHALL abortar el comando con un mensaje que nombre la variable ausente, y THE
   SYSTEM SHALL **no** caer silenciosamente al mock.
3. WHEN `--provider` reciba un valor que no sea `mock` ni `channex`, THE SYSTEM SHALL
   rechazarlo con el uso del comando y un código de salida distinto de cero.
4. THE SYSTEM SHALL declarar en `.env.example` únicamente los **nombres** de las
   variables nuevas, nunca un valor (regla 8 de `steering/security.md`).
5. WHERE el código implemente esta selección, THE SYSTEM SHALL dejar constancia de que
   es un stopgap de dev/staging y de que `pms-beds24-adapter` lo sustituye por la
   `PMSAdapterFactory` con resolución por propiedad (ADR 0006 decisión 7).

### R4 — Captura reproducible de payloads reales como fixtures

**As a** desarrollador, **I want** los cuerpos reales que devuelve Channex versionados
como fixtures, **so that** pueda escribir y mantener los tests del adapter sin depender
de la cuenta de staging ni de la red.

Acceptance criteria:

1. WHEN se ejecute el script de sondeo contra staging, THE SYSTEM SHALL escribir a disco
   los cuerpos **crudos** de reserva, de mensaje y de webhook tal como los devuelve el
   proveedor.
2. THE SYSTEM SHALL anonimizar todo dato personal de los fixtures que se versionan
   (nombre, email, teléfono, documento), conservando forma y tipos.
3. WHEN los fixtures se usen en tests, THE SYSTEM SHALL ejecutarlos sin ninguna llamada
   de red.
4. IF el script necesita credenciales, THEN THE SYSTEM SHALL leerlas del entorno y THE
   SYSTEM SHALL rechazarlas por argumento de línea de comandos, que quedaría en el
   historial del shell.

### R5 — Una reserva end-to-end real, de Booking.com a nuestra base de datos

**As a** desarrollador del backend, **I want** que una reserva creada en el entorno de
test de Booking.com llegue hasta nuestro `TimelineEvent`, **so that** quede demostrado
que la cadena completa funciona contra una OTA de verdad y no solo contra un CSV.

Acceptance criteria:

1. WHEN se cree una reserva desde el entorno de test de Booking.com sobre una propiedad
   de test de Channex, THE SYSTEM SHALL recuperarla mediante `list_reservations` del
   `ChannexAdapter` y persistirla ejecutando `pms_sync <tenant>` contra la base local.
2. THE SYSTEM SHALL registrar la evidencia en `docs/channex-staging.md`: la reserva
   creada, el payload recibido (anonimizado) y el `TimelineEvent` resultante.
3. IF Channex no concede el acceso al entorno de test de Booking.com dentro del alcance
   temporal de este change, THEN THE SYSTEM SHALL registrar el bloqueo en `BLOCKED.md`
   como `decision`, y THE SYSTEM SHALL entregar R1–R4 y R6 igualmente — R5 es la única
   parte que depende de un tercero.

### R6 — Hallazgos y límites medidos, como entrada de diseño

**As a** persona que va a diseñar `pms-beds24-adapter`, **I want** los límites reales de
un PMS documentados con evidencia, **so that** el diseño no se construya sobre supuestos
de documentación de proveedor.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en `docs/channex-staging.md` los límites observados de la
   API —paginación, límite de tasa y la cabecera que lo expone si existe, latencia
   típica— y el **desorden de webhooks** que ADR 0006 atribuye a Channex, cada uno con la
   observación que lo respalda.
2. WHERE un hallazgo contradiga lo que afirman ADR 0006 o PRD §16, THE SYSTEM SHALL
   registrarlo como desviación siguiendo la convención de ADR 0005: se anota, no se
   edita el documento original.
3. THE SYSTEM SHALL enumerar qué queda por medir en Beds24 y **no** se puede extrapolar
   de Channex, para que `pms-beds24-spike` arranque con su lista ya cerrada.

## Out of scope

- **Todo lo de Beds24** — cuenta, `X-RequestCost`, latencia de sus webhooks, sus
  fixtures: sigue siendo `pms-beds24-spike`, que arranca cuando este change cierre.
- **El endpoint de recepción de webhooks** (`POST /api/v1/webhooks/…`) y la regla 12 de
  `steering/security.md` → `reservations-webhooks`. Aquí los webhooks de Channex se
  **observan** (apuntándolos a un capturador externo para producir el fixture de R4), no
  se recibe ninguno en nuestra API.
- **`PMSAdapterFactory`, credenciales por propiedad en base de datos y cifrado Fernet**
  → `pms-beds24-adapter`. La credencial de este change vive en el entorno, que es el caso
  que la regla 3 excluye de forma expresa.
- **Separación de `PMSMessagingPort` respecto de `PMSAdapter`** (ADR 0006 decisión 3) →
  `pms-beds24-adapter`. Este adapter implementa los dos métodos que el puerto declara hoy.
- **Los otros seis métodos de PRD §16** (`update_price`, `block_dates`,
  `get_availability`, `list_properties`, `get_messages`, `send_message`): llegan con
  `revenue` y `messaging-ai`, como ya documenta el propio puerto.
- **Mensajería** y la app de pago `channex_messages`.
- **Conectar cualquier cuenta real de OTA** (Airbnb, Booking.com o Expedia de
  producción) — prohibido de forma explícita por R1.2.
- **Reabrir ADR 0006.** Beds24 sigue siendo el proveedor del MVP; esto es una herramienta
  de validación, no una migración.

## Affected specs

- `sdd/specs/reservations.md` — documenta hoy `MockPMSAdapter` como única implementación
  del puerto y `pms_sync <tenant>` con el adapter fijado en código; las dos cosas cambian.
- `sdd/specs/local-environment.md` — variables nuevas en `.env.example`.
- `sdd/specs/pms-channex-staging.md` *(no existe aún — se creará al archivar)* — el
  comportamiento del `ChannexAdapter` y el contrato del entorno de staging.

**Steering que quedará desalineado y hay que tocar al archivar** (no son specs, pero se
apuntan aquí para que no se pierdan):

- `steering/security.md` regla 8 — su enumeración dice que el `PMS_API_KEY` de
  bootstrap/mock es la **única** credencial de PMS que vive en el entorno; este change
  añade la de Channex staging y la regla necesita una línea que lo recoja.
- `steering/product.md` — dice "Channex en fase SaaS", que sigue siendo cierto **para
  producción**; conviene una línea que distinga el uso de su staging como entorno de
  validación desde ya, tal como prescribe ADR 0006 decisión 2.

## Preguntas abiertas para `/sdd:design`

1. **Dónde vive el `ChannexAdapter`.** `app/integrations/infrastructure/` junto a
   `mock_pms.py` es lo que dicta `steering/backend.md`, pero con dos proveedores conviene
   decidir ya si cada uno tiene su subpaquete.
2. **Forma exacta de la selección de proveedor.** Una variable `PMS_PROVIDER` global
   (la de PRD §22, que ADR 0006 sustituye por resolución por propiedad y que hoy **no
   existe en el código**) o un flag del CLI. Elegir la que menos deuda deje cuando llegue
   la factory.
3. **Cliente HTTP y política de reintentos** frente a la API de Channex, y si el
   `since` del puerto se traduce a su filtro de fecha de modificación o de creación
   —cambia el significado del sync incremental.
