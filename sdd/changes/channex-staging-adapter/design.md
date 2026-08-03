# Design: channex-staging-adapter

## Context

El puerto vive en `backend/app/integrations/domain/ports.py` y declara **dos** métodos:
`list_reservations(since, property_external_id=None) -> list[ReservationDTO]` y
`get_reservation(external_id) -> ReservationDTO | None`. Su única implementación es
`backend/app/integrations/infrastructure/mock_pms.py`, y el único sitio del sistema que
construye un adapter es `backend/app/integrations/cli/pms_sync.py:74`, a pelo. Aguas
abajo, `SyncReservationsFromPmsUseCase`
(`backend/app/integrations/application/use_cases.py:32`) resuelve la propiedad por
`Property.pms_external_id` (`String(200)`, nullable) y entrega las filas a
`ReservationIngestor`, que ya es idempotente por `(tenant_id, external_pms_id)` y
convierte un fallo de fila en una fila reportada en vez de abortar la corrida.

Dos hechos del repo que condicionan el diseño y no son evidentes: **`httpx` es hoy una
dependencia de desarrollo**, no de runtime (`backend/pyproject.toml:39`, bloque
`[dependency-groups].dev`); y **no existe ningún directorio de fixtures en disco** — los
tests de CSV construyen su contenido en línea. Además `tests/test_layering.py` verifica
por AST la regla de dependencia sobre `app/*/domain/` y `app/*/application/`, así que
todo lo nuevo tiene que caer en `infrastructure/`.

Esta investigación se hizo **contra la documentación real de Channex**, no contra
supuestos, y encontró un desencaje de forma que domina el resto del diseño (D1).

## Decisiones

### D1 — `list_reservations` se implementa sobre `GET /bookings`, no sobre el feed de revisions — y el hueco que eso deja es un entregable, no un descuido

**Chosen:** el adapter consulta `GET /bookings` con
`filter[inserted_at][gte]=<since>`, pagina hasta agotar y **no toca el feed de
revisions**. El feed se *observa* en el script de sondeo (R4/R6) y su desencaje con el
puerto se documenta como hallazgo de primera clase.

Por qué importa: Channex prescribe para integraciones PMS el **Booking Revisions Feed**
(`GET /booking_revisions/feed`, cola de revisions no confirmadas, con
`POST /booking_revisions/:id/ack` obligatorio **en menos de 30 minutos** o llegan avisos
por correo). Eso es una cola con acuse, no un pull por ventana temporal, y **rompe dos
propiedades que nuestro puerto da por sentadas**: que `since` es quien manda sobre el
tiempo, y que el sync es **repetible** — una vez haces `ack`, esa ventana no se puede
releer. Un adapter que hiciera `ack` dentro de `list_reservations` convertiría una
lectura en una escritura destructiva contra el proveedor, y una re-ejecución del comando
dejaría de ser inocua.

El precio de elegir `/bookings` está medido y es concreto: los filtros disponibles son
`filter[arrival_date]`, `filter[departure_date]` y `filter[inserted_at]` — **no existe
filtro por fecha de modificación**. Es decir, `list_reservations(since)` verá las
reservas *creadas* después de `since` y **no verá una modificación ni una cancelación**
de una reserva anterior. Para R5 (una reserva nueva de Booking.com que llega hasta el
`TimelineEvent`) es suficiente y correcto. Para un sync incremental de producción **no lo
es**, y esa es exactamente la clase de sorpresa que este change existe para encontrar:
va a R6 como hallazgo, y es entrada de diseño directa de `pms-beds24-adapter` y de
`reservations-webhooks`.

Rejected: implementar sobre el feed **con** `ack` — mete una escritura destructiva
dentro de una lectura y hace el sync no repetible.
Rejected: implementar sobre el feed **sin** `ack` — evita la escritura pero acumula la
cola y dispara los avisos de los 30 minutos, además de ignorar el `since` que el puerto
promete respetar.
Rejected: `filter[arrival_date][gte]` como aproximación a `since` — cambia el significado
del parámetro (llegada, no alta) y perdería toda reserva de última hora para hoy.

### D2 — El adapter vive en un subpaquete `infrastructure/channex/`

**Chosen:** `backend/app/integrations/infrastructure/channex/` con `client.py` (HTTP,
paginación, traducción de errores, redacción de la credencial), `adapter.py` (implementa
`PMSAdapter`) y `mapping.py` (Channex → `ReservationDTO`). `mock_pms.py` se queda donde
está. Con un cliente HTTP real, paginación y una tabla de mapeo, un módulo plano de
varios cientos de líneas mezcla tres responsabilidades; y `pms-beds24-adapter` seguirá
esta misma forma, así que la establece este change.

Rejected: `channex_pms.py` plano junto a `mock_pms.py` — simétrico con el mock, pero el
mock no tiene ni transporte ni mapeo.

### D3 — La selección de proveedor es un flag del CLI, no una variable global de aplicación

**Chosen:** `pms_sync` acepta `--provider {mock,channex}` con **`mock` por defecto**, y
es el único punto del sistema que puede construir el `ChannexAdapter`. Las credenciales
(`CHANNEX_API_KEY`, `CHANNEX_BASE_URL`) sí son settings, porque son configuración; la
*elección* no lo es.

El motivo es evitar deuda con nombre: PRD §22 definía un `PMS_PROVIDER` global y **ADR
0006 lo retiró expresamente** en favor de resolución por propiedad. Reintroducir esa
variable ahora resucita un concepto ya descartado y garantiza que alguien la lea dentro
de seis meses como si fuera el mecanismo real. Un flag de un comando de operador no puede
filtrarse a la aplicación ni a la suite, y R3.1 ("por defecto nada cambia") se cumple por
construcción en vez de por configuración.

**Esto ajustó el mecanismo de R3.1/R3.2**, que estaban escritos como variable de entorno:
el proposal quedó enmendado en el gate de esta fase (OQ2, resuelta), y R3 ganó un tercer
criterio para el valor inválido de `--provider`.

Rejected: `PMS_PROVIDER` en `Settings` — resucita el global que ADR 0006 retiró.
Rejected: una `PMSAdapterFactory` ya — es explícitamente de `pms-beds24-adapter`, y una
factory que solo resuelve por variable global es la forma equivocada de la definitiva.

### D4 — `httpx` pasa a dependencia de runtime

**Chosen:** mover `httpx` de `[dependency-groups].dev` a `[project].dependencies` en
`backend/pyproject.toml`. El adapter lo necesita en ejecución; hoy solo está porque
`AsyncClient` se usa en los tests.

Es una **dependencia de runtime nueva**, lo que dispara el trigger de revisión extra de
`steering/security.md` ("dependencias nuevas"). El riesgo real es bajo —ya está en el
lockfile, ya la arrastra FastAPI en su ecosistema y ya se ejecuta en CI— pero el
movimiento tiene que ser explícito y la imagen de Docker tiene que instalarla en el grupo
correcto, no por accidente del grupo `dev`.

Rejected: `urllib`/`aiohttp` — uno no es async, el otro es una dependencia nueva de
verdad cuando ya tenemos httpx a un renglón de distancia.

### D5 — El puerto gana un contrato de error, porque hoy no tiene ninguno

**Chosen:** un `PmsUnavailableError` en `app/integrations/domain/` (vocabulario del
puerto, no de Channex), que el `ChannexAdapter` lanza ante error de transporte, `401`,
`429` o `5xx`; `pms_sync` lo captura y sale con código distinto de cero y un mensaje en
inglés.

R2.3 pide "la misma clase de error que el resto del sistema ya espera del puerto" y la
investigación encontró que **esa clase no existe**: `MockPMSAdapter` no lanza nunca, y
`app/integrations/api/errors.py` solo cubre los errores de fichero del CSV. Definirla en
`domain/` es lo que impide que `pms_sync` tenga que importar `infrastructure/channex/`
para saber qué capturar.

**Higiene de credencial, que es requisito y no estilo (R2.3):** el cliente redacta
`user-api-key` en cualquier `repr`, log o mensaje de excepción. `httpx` incluye las
cabeceras en la representación de sus errores de forma natural, así que esto se
implementa y **se testea**, no se confía.

Rejected: dejar que `httpx.HTTPError` suba tal cual — acopla el CLI al transporte y
arrastra la cabecera con la clave dentro del traceback.

### D6 — Paginación explícita con tope, y el tope **falla**, no trunca

**Chosen:** `list_reservations` recorre las páginas usando `meta.{total,page,limit}`
hasta agotar, con un tope de páginas configurable. Al alcanzarlo **lanza**
`PmsUnavailableError` en vez de devolver lo que lleve.

El `limit` por defecto de Channex es **10**, así que paginar no es opcional: sin ello
todo sync ve como mucho diez reservas. Y truncar en silencio dentro de un sync es
indistinguible de "el PMS no tenía más", que es la peor forma de fallo posible aquí —
reservas ausentes que nadie detecta.

Rejected: pedir un `limit` enorme y no paginar — depende de un máximo del proveedor que
no está documentado y que puede cambiar sin avisar.

### D7 — Mapeo: `unique_id` como identidad, y ningún canal desconocido tumba una fila

**Chosen:**

- `external_id` ← **`unique_id`** (código de OTA + código de reserva, **estable entre
  revisions**), nunca `system_id`, que es único *por revision*. Es la decisión que
  sostiene la idempotencia por `(tenant_id, external_pms_id)` que `ReservationIngestor`
  ya implementa: con `system_id`, cada modificación crearía una reserva nueva.
- `property_external_id` ← el `property_id` (UUID) de Channex, que se escribe en
  `Property.pms_external_id` de la propiedad de test (`String(200)`, sobra sitio).
- `channel` ← nombre de OTA de Channex traducido a `ReservationChannel`, con
  **`OTHER` como destino de lo no reconocido**. `ReservationChannel.parse` lanza ante un
  valor desconocido y el ingestor lo convierte en fila saltada: dejar pasar el literal de
  Channex haría que una OTA nueva descarte reservas válidas en vez de importarlas con el
  canal genérico que el enum ya tiene para esto.
- `ota_commission` ← solo lo hay para Booking.com y Airbnb; en el resto `None`, no cero
  (R2.4) — un cero es una afirmación falsa sobre la comisión.
- `raw_payload` ← el elemento `data` completo, sin tocar, como manda el docstring del DTO.

Rejected: `system_id` como `external_id` — rompe la idempotencia en cuanto llega una
modificación.
Rejected: propagar el literal de canal de Channex y dejar que `parse` decida — convierte
un canal no mapeado en pérdida de datos.

#### D7 bis — corregido contra el payload real (2026-08-03)

Los fixtures de la tarea 2.3 se capturaron de la cuenta de staging y **contradicen cuatro
cosas** que D7 daba por buenas desde la documentación. Se corrigen aquí en vez de
reescribir D7, para que quede el rastro de qué se supuso y qué se midió.

1. **`system_id` no existe en `/bookings`.** Las claves reales de identidad son
   `unique_id`, `booking_id`, `revision_id` e `id`. `unique_id` sigue siendo la elección
   correcta —llega prefijado por OTA (`BDC-…`, `OFL-…`), estable entre revisions— pero la
   advertencia de D7 nombraba un campo que en esta colección no está.

2. **`ota_commission` nunca es `null`: siempre es un string, y `"0.00"` cuando no hay
   dato.** R2.4 prohibía el cero *porque afirma en falso que no hubo comisión*, y el
   proveedor hace exactamente eso. Como el contrato del puerto sí distingue —`Decimal |
   None`, donde `None` es "el proveedor no informa"— **la traducción vive en el adapter**:
   si `ota_name` está entre las OTAs de las que Channex informa comisión (Booking.com,
   Airbnb) el valor se respeta, incluido un cero legítimo; en cualquier otro caso `None`.
   Una OTA nueva y desconocida cae del lado de `None`, que es el lado seguro.

3. **`status` usa el vocabulario de Channex**: `new`, `modified`, `cancelled`. Ninguno
   existe en `ReservationStatus`, y `parse_ingested` **lanza** ante un valor desconocido,
   que el ingestor convierte en fila saltada — sin mapeo explícito el sync importaría
   **cero reservas** informando cada una como error. El adapter traduce
   `new`/`modified` → `CONFIRMED` y `cancelled` → `CANCELLED`; el argumento para `new` ya
   está escrito en el docstring de `parse_ingested` ("una reserva que llega de un feed de
   PMS es un booking que alguien ya aceptó").

   **Asimetría deliberada frente al canal**: un canal desconocido va a `OTHER` para no
   perder la reserva, pero un **status** desconocido se deja pasar tal cual para que
   `parse_ingested` falle y la fila se reporte. Un canal mal puesto no mueve nada; un
   status mal puesto conduce la `PropertyStateMachine`.

4. **`inserted_at` es UTC serializado sin zona, y el filtro ignora el offset que le
   mandes.** Medido contra la API:

   | `filter[inserted_at][gte]` | filas |
   |---|---|
   | `2026-08-03T09:00:00` | 2 |
   | `2026-08-03T09:00:00Z` | 2 |
   | `2026-08-03T11:00:00+02:00` | **0** |

   Las tres cadenas nombran instantes que deberían incluir las dos reservas (creadas a las
   09:53 UTC); la tercera devuelve cero porque Channex **compara el reloj de pared
   literal** y descarta el `+02:00`. Enviar un ISO tz-aware desde Madrid en verano abre un
   **agujero de dos horas** en cada sync, silencioso y sin rastro en la documentación. El
   adapter convierte `since` a UTC y lo serializa **sin offset**.

### D8 — Primer directorio de fixtures en disco del repo

**Chosen:** `backend/tests/integrations/fixtures/channex/*.json`, un fichero por forma
capturada (reserva, revision, mensaje, webhook), cargados por un helper mínimo en
`tests/integrations/conftest.py`. **La anonimización la hace el script en el momento de
capturar** (R4.2), no una pasada manual posterior: un fixture que se anonimiza a mano
acaba commiteado con datos reales el día que alguien tenga prisa.

Rejected: contenido en línea como hacen los tests de CSV — un payload real de Channex son
decenas de campos anidados y en línea es ilegible.

### D9 — El script de sondeo vive fuera de `app/`

**Chosen:** `backend/scripts/channex_probe.py`. Es una herramienta desechable de captura,
no superficie de la aplicación, y no debe viajar en el paquete. Lee credenciales **solo
del entorno** (R4.4) y escribe los ficheros ya anonimizados.

Captura cuatro formas: reserva (`/bookings`), **revision (`/booking_revisions/feed`, una
sola lectura y sin `ack`)**, mensaje y webhook. La del feed no la consume ningún código
de este change — se captura porque es la entrada de diseño de `reservations-webhooks` y
reconstruir el escenario más adelante cuesta más que el fichero (resolución de OQ3).

Rejected: `app/integrations/cli/channex_probe.py` junto a `pms_sync.py` — consistente,
pero convierte un script de un solo uso en API del paquete desplegado.

### D10 — Los webhooks se observan, no se reciben

**Chosen:** se configura un webhook de Channex apuntando a un capturador externo, con el
único fin de producir el fixture de R4.1 y observar el desorden de R6.1. **Nuestra API no
expone ninguna ruta entrante en este change.**

La documentación de Channex confirma literalmente lo que ADR 0006 afirma y lo que la
**regla 12** de `steering/security.md` regula: no hay firma criptográfica, la
recomendación es una cabecera de secreto compartido propia, hay reintentos con backoff
exponencial hasta 10 intentos, y *"Sequence of incoming webhook calls can be different
from sequence of events which trigger that calls"* — con la instrucción explícita de
tratar el webhook como disparador y releer el estado por API. Construir la ruta aquí
significaría cumplir la regla 12 entera (autenticación por cabecera con valor por tenant,
ruta con token opaco, límite de tasa, tope de cuerpo, relectura encolada y coalescida),
que es el alcance completo de `reservations-webhooks`.

Un matiz que **desvía de lo que ADR 0006 asumía** y va a R6.2: Channex **sí tiene API de
configuración de webhooks** (incluido `is_global: true` con `property_id: null`), a
diferencia de Beds24, cuya configuración es manual por propiedad desde su panel.

### D11 — La propiedad de test se cablea a mano, y consta

**Chosen:** el `property_id` de Channex se escribe en `Property.pms_external_id` mediante
un paso documentado en el runbook (`docs/channex-staging.md`), no mediante migración ni
cambio en `app/cli/bootstrap.py`. Es una propiedad de un entorno de staging de un
proveedor que no es el del MVP; meterla en el bootstrap la convertiría en parte del
arranque de todo el mundo.

Rejected: extender `bootstrap.py` — contamina el arranque estándar con un proveedor de
dev.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Puerto / dominio | `backend/app/integrations/domain/errors.py` *(nuevo)* | `PmsUnavailableError` (D5) |
| Adapter | `backend/app/integrations/infrastructure/channex/{__init__,client,adapter,mapping}.py` *(nuevos)* | Cliente HTTP con paginación y redacción, `ChannexAdapter`, tabla de mapeo (D1, D2, D6, D7) |
| CLI | `backend/app/integrations/cli/pms_sync.py` | `--provider {mock,channex}` por defecto `mock`; captura de `PmsUnavailableError` → exit ≠ 0 (D3, D5) |
| Config | `backend/app/core/config.py` | `channex_api_key: str = ""`, `channex_base_url: str = "https://staging.channex.io/api/v1"`, tope de páginas |
| Dependencias | `backend/pyproject.toml` | `httpx` de `dev` a `[project].dependencies` (D4) |
| Sondeo | `backend/scripts/channex_probe.py` *(nuevo)* | Captura y anonimiza payloads (D9) |
| Fixtures | `backend/tests/integrations/fixtures/channex/*.json` *(nuevos)* | Payloads reales anonimizados (D8) |
| Tests | `backend/tests/integrations/test_channex_adapter.py` *(nuevo)*, `conftest.py`, `test_pms_sync_cli.py` | Mapeo, paginación, errores, redacción de la clave, default del flag |
| Entorno | `.env.example` | Nombres sin valor de `CHANNEX_API_KEY` / `CHANNEX_BASE_URL` |
| Docs | `docs/channex-staging.md` *(nuevo)*, `docs/README.md` | Runbook, evidencia end-to-end, límites medidos, hallazgos |

`docker-compose.yml` **no cambia**: el servicio `backend` ya lleva `env_file: .env`, y el
fallo rápido de R3.2 es en código, no un `${VAR:?}` de compose.

## Data & interfaces

**Esquema de base de datos: ninguno.** No hay migración. `Property.pms_external_id` ya
existe y ya admite un UUID.

**API HTTP propia: ninguna.** No se añade ni se modifica ninguna ruta, así que
`openapi.json` no se mueve y `tests/test_openapi_contract.py` no cambia.

**Contrato del proveedor (medido, no supuesto):**

| Aspecto | Valor |
|---|---|
| Base URL staging | `https://staging.channex.io/api/v1` |
| Autenticación | cabecera `user-api-key`, emitida en Organisation → API Keys, con alcance a todas las propiedades o a un subconjunto |
| Envoltorio | `{"meta": {"total","page","limit"}, "data": [{"type","id","attributes"}]}` |
| Errores | `{"errors": {"code","title"}}` |
| Paginación | `?page=N&limit=N`, **default 10** |
| Filtros de `/bookings` | `filter[arrival_date]`, `filter[departure_date]`, `filter[inserted_at]` (`[gte]`/`[lte]`) — **no hay filtro por modificación** |
| Identidad | `unique_id` estable entre revisions; `system_id` por revision |
| Límite de tasa | **no documentado** — es justo lo que R6.1 manda medir |

**Variables de entorno nuevas:** `CHANNEX_API_KEY` (nombre sin valor, regla 8), y
`CHANNEX_BASE_URL` (no es secreto; lleva default a staging **a propósito**, para que un
despiste de configuración apunte a staging y nunca a producción).

## Risks & mitigations

- **El sync no detecta modificaciones ni cancelaciones** (D1). No es un bug del adapter,
  es la forma de la API elegida. Mitigación: se documenta como hallazgo de R6 y R5 se
  demuestra con una reserva **nueva**, que es lo que el criterio pide. No se debe usar
  este adapter como base de un sync de producción.
- **Fuga de la API key en un traceback** — `httpx` arrastra cabeceras en sus errores.
  Mitigación: redacción en el cliente **con test propio** (D5), no confianza.
- **Datos personales reales en los fixtures.** Los payloads del entorno de test de
  Booking.com pueden traer nombres y correos. Mitigación: anonimización en captura (D8) y
  revisión del diff antes de commitear; es materia del panel de seguridad en `/sdd:review`.
- **Suite de CI dependiente de la red.** Mitigación: R2.5 lo prohíbe; los tests del
  adapter van contra `httpx.MockTransport` alimentado por los fixtures, sin salida.
- **`httpx` como runtime nuevo** (D4) — trigger de revisión extra de `security.md`.
  Mitigación: ya en lockfile y en CI; el diff de `pyproject.toml` se revisa explícitamente.
- **R5 depende de un tercero** — ya está previsto en el propio criterio R5.3 (bloqueo a
  `BLOCKED.md`, el resto se entrega).
- **Conectar por error una OTA real.** Es el riesgo con peor consecuencia de todo el
  change: dejaría dos anuncios que están vendiendo con un channel manager equivocado.
  Mitigación: R1.2 lo convierte en criterio de aceptación verificable, no en una nota.

## Open questions

Las tres se resolvieron en el gate de `/sdd:design` (2026-08-03). Se dejan aquí con su
resolución en vez de borrarlas: la alternativa descartada es la mitad de la información.

1. ~~**¿`/bookings` o el feed de revisions?**~~ (D1) → **`/bookings` con
   `filter[inserted_at][gte]`**. Pesa más mantener la lectura idempotente y repetible que
   ser fiel a lo que Channex prescribe para un PMS de producción, porque este adapter no
   va a producción. Descartado el feed sin `ack`: acumula la cola, dispara los avisos de
   30 minutos e ignora el `since` que el puerto promete respetar. **El hueco de las
   modificaciones y cancelaciones es ahora un entregable de R6**, no una limitación
   tácita.
2. ~~**¿Flag de CLI o variable de entorno?**~~ (D3) → **flag `--provider`**, para no
   resucitar el `PMS_PROVIDER` que ADR 0006 retiró. Descartado `PMS_SYNC_PROVIDER`:
   habría dejado R3.1/R3.2 intactas, pero a cambio de config global que se lee mal.
   **Consecuencia asumida: R3.1 y R3.2 del proposal se reescriben en términos de flag**
   (hecho en la misma sesión).
3. ~~**¿Fixture del `booking_revisions` sin consumirlo?**~~ → **sí**. El script de sondeo
   hace **una** lectura del feed —sin `ack`— solo para capturar su forma. Es la entrada
   de diseño de `reservations-webhooks` y volver a montar el escenario después cuesta más
   que el fichero JSON.
