# Channex staging — runbook y hallazgos

Runbook del sandbox de Channex y **registro de lo que se midió al operarlo**, el 2026-08-03.
No describe una capacidad disponible a demanda: la validación end-to-end contra Booking.com vivo
fue un tiro único que dependió de ganar un turno sobre un hotel de test compartido, y lo que
costó está medido en §«Reserva end-to-end contra Booking.com». Este documento es la mitad del
entregable del change `channex-staging-adapter`: es un spike, así que lo que se aprende vale
tanto como el código.

Decisión de fondo: [ADR 0006](adr/0006-pms-channel-manager-provider.md) elige **Beds24** para
el MVP y sitúa Channex en fase SaaS. Nada de lo que hay aquí reabre eso — el `ChannexAdapter`
es una **herramienta de validación de dev/staging**, no el proveedor de producción. Lo que
Channex aporta y ningún otro puede es acceso al entorno de test de Booking.com: no existe
sandbox de OTA en ninguno de los once proveedores que ese ADR evaluó.

---

## ⚠️ Regla dura: qué no se conecta nunca

**Solo se usan las propiedades de test de Channex. La cuenta real de Airbnb no se conecta a
este sandbox, ni a ningún otro.**

El motivo no es prudencia genérica. **Airbnb admite un único channel manager por cuenta** y
Channex falla en duro si ya hay otro conectado. Enganchar aquí los pisos reales obligaría a
desconectarlos después para que Beds24 —el proveedor elegido para el MVP— pueda hablar con
ellos, y eso abre una **ventana de corte sobre dos anuncios que están vendiendo**. Es el
riesgo con peor consecuencia de todo el change, y por eso es un criterio de aceptación
verificable (R1.2) y no una nota al pie.

Lo mismo aplica a la cuenta real de Booking.com. Los hoteles de test de Booking.com
(§"Reserva end-to-end") **no son** REDES11 ni PAJARITOS8: son hoteles ficticios del entorno de
pruebas de la OTA.

---

## Alta de la cuenta

`staging.channex.io` — gratis, self-serve, **sin tarjeta y sin caducidad**. Esa es la razón por
la que se abre antes que Beds24, cuyo trial de 14 días empieza a contar al registrarse: se
aprende el modelo de datos de un Channel Manager aquí para que los 14 días de Beds24 vayan
íntegros a *medir*.

### Credencial

Organisation → API Keys → `Create new API Key`. Se copia una sola vez.

Va en el `.env` de la raíz como `CHANNEX_API_KEY`, **solo el nombre en `.env.example`**
(regla 8 de `sdd/steering/security.md`). El contenedor la recibe por `env_file: .env`, así que
tras añadirla hace falta `docker compose up -d backend` — `env_file` se lee al **crear** el
contenedor, no al arrancarlo.

> **No aplica la regla 3 (Fernet en reposo)**: esa regla cubre credenciales de proveedor
> «que no vivan en el entorno», y esta vive ahí. Las credenciales cifradas por propiedad
> llegan con `pms-beds24-adapter`, que es el change donde nacen esas columnas.

**Desmarca «Access to all properties» y acota la key a la propiedad del sandbox.** El panel
ofrece *todas las propiedades* por defecto, y la primera versión de este runbook decía que
«cualquiera de las dos sirve» — lo cual contradice de lleno la **regla 3** de
`sdd/steering/security.md`: *«Las de cuenta u organización son las más peligrosas, no las menos:
una sola concede escritura sobre **todas** las propiedades de esa cuenta, no sobre una»*.

No es teórico aquí: dos scripts de este change **escriben** con esa key —
`channex_bootstrap.py` crea propiedades, rate plans y reservas, y `channex_claim_test_hotel.py`
crea y vincula canales—, así que una key de organización filtrada concede escritura sobre toda
la cuenta en vez de sobre un sandbox. La key amplia solo se justifica si de verdad hace falta
operar varias propiedades, y entonces conviene decirlo explícitamente.

### Provisión del sandbox — por API, no a mano

```bash
docker compose exec backend uv run python scripts/channex_bootstrap.py
```

Crea (o reusa) propiedad, room type, rate plan, instala las apps necesarias y siembra dos
reservas de test. **Es idempotente**: una segunda corrida imprime `reused` y no duplica nada.

Existe como script y no como lista de clics por dos razones: la tarea 1.1 exige que el alta sea
**reproducible**, y una lista de siete campos que rellenar en un panel no lo es.

Dos guards que conviene no desactivar, los dos endurecidos tras encontrar que su primera
versión no protegía:

- **Apps por allowlist** (`KNOWN_FREE_APPS`), no por «no tiene precio». La primera versión
  abortaba solo si el catálogo reportaba un precio, y **en el único caso para el que existía no
  disparó**: `channex_messages` es de pago según ADR 0006 y staging la reporta con
  `price: null`. Un script de setup no debe poder contratar nada, y la ausencia de precio no
  demuestra que sea gratis.
- **Host exacto** (`ALLOWED_HOSTS`), no `"staging" in base_url`. Esa comprobación aceptaba
  `https://app.channex.io/api/v1?env=staging` —una cuenta viva— y
  `https://staging.channex.io.example.net/`, que además habría recibido la API key en la
  cabecera. El script escribe de verdad (propiedades, rate plans, reservas), así que es el único
  control entre un `CHANNEX_BASE_URL` mal puesto y provisionar datos de prueba en producción.

El título de la propiedad es la **clave de idempotencia**. Si se renombra en el panel hay que
cambiar también `PROPERTY_TITLE` en el script, o la siguiente corrida creará una propiedad
duplicada en vez de reusar la existente.

> El sandbox se llama `AutoHostAI Channex Sandbox (test only)`. La primera versión se llamaba
> `AutoHostAI STAGING TEST — REDES11` y **fue un error**: bautizar un sandbox con el nombre de
> un piso que está vendiendo llevó directamente a la pregunta «¿este enlace de Booking.com es
> de mi apartamento?». No se reutilizan nombres de anuncios reales.

### `EXTERNAL_DEPENDENCY`

- **App `booking_crs`** — sin ella `POST /bookings` responde **403** y el error no lo explica.
  Se instala por API (`POST /applications/install`, código `booking_crs`); en staging figura sin
  precio.
- **App `channex_messages`** — instalada el 2026-08-03 por decisión explícita del operador.
  **En staging figura `price: null`, pero ADR 0006 la documenta como de pago y por propiedad**:
  el precio de staging no dice nada del de producción.
- **Mapeo de canal** — *no está en la API pública*: «Access to the channel API is only for
  Whitelabel accounts». Es el único paso irreducible de panel.
- **Hoteles de test de Booking.com** — disponibles pero **por turnos**, ver abajo.

### Cablear el sandbox a una propiedad de AutoHostAI

El `property_id` que imprime el script se escribe en `Property.pms_external_id` de la propiedad
que deba sincronizar desde este sandbox. **Un paso puntual documentado, no una migración ni un
cambio en `app/cli/bootstrap.py`**: es una propiedad de un proveedor que no es el del MVP y no
tiene nada que hacer en el arranque de todo el mundo.

### Sincronizar

```bash
docker compose exec backend uv run python -m app.integrations.cli.pms_sync <tenant-uuid> --provider channex
```

**Desde `pms-provider-resolution`, `--provider` es un override de operador y no el mecanismo.**
Sin el flag, cada propiedad resuelve el proveedor que declara en `properties.pms_provider`, y la
que no declara ninguno cae a `MockPMSAdapter` — así que para quien no configure nada sigue sin
cambiar nada, pero por una razón distinta. Con el flag, el comando anuncia por salida estándar que
está ignorando lo que cada propiedad guarda. Para usar Channex de forma permanente, asigna el
proveedor a la propiedad en vez de pasar el flag.

Con `--provider channex` y sin `CHANNEX_API_KEY` **aborta nombrando la variable** en vez
de caer al mock: un fallback silencioso imprimiría «created 0, updated 0», indistinguible de un
PMS vacío, y una credencial mal puesta parecería un sync correcto para siempre.

El flag es un **stopgap declarado**. ADR 0006 retiró el `PMS_PROVIDER` global de PRD §22 en
favor de resolución **por propiedad** con credenciales cifradas; eso es `pms-beds24-adapter`,
que sustituye esta función por una `PMSAdapterFactory`. Vive en un flag de comando y no en
`Settings` precisamente para que no pueda filtrarse a la aplicación ni resucitar un nombre de
configuración ya descartado.

---

## Reserva end-to-end contra Booking.com

**No hay que pedir nada a soporte.** Channex publica hoteles de test ya conectados en staging,
self-serve — lo que corrige una premisa de ADR 0006, que asumía propiedades «prestadas» previa
petición ([guía oficial](https://docs.channex.io/guides/test-account-for-booking.com)).

**Y algunos IDs no aceptan reservas en absoluto**: la ficha de cada hotel en esa misma guía puede llevar un aviso `Bookings not possible currently for this ID` — `10745030` lo tiene, y por eso Booking.com rechazó todas las tarjetas de test contra él. La lista resumen del formulario de Channex NO muestra ese aviso, solo la ficha por hotel; conviene leerla antes de gastar un turno.

Pero **son un pool con reserva por franjas horarias, no recursos a demanda**. Medido el
2026-08-03 a las ~12:30: los **ocho** IDs figuraban simultáneamente como *"In use until August
3rd 2026, HH:MM"* y el intento devolvía *"Incorrect Connection — This Hotel ID is already in
use"*. A las 13:50, la hora exacta en que el ID en EUR debía liberarse, guardar el canal
devolvió *"channel with same settings already exists"* — con **cero canales en nuestra cuenta**,
comprobado por API. Es decir: **la comprobación de unicidad es global entre cuentas**, otro
integrador se lo había llevado en el intervalo, y **no hay cola ni reserva de turno**.

**Y el turno que se gana es el resto de la franja de otro, no una ventana nueva.** El panel
anuncia un **instante absoluto** (*"In use until August 3rd 2026, HH:MM"*) y en ningún sitio una
duración, así que lo que queda por delante depende de cuándo caduque el arrendamiento ajeno, no de
cuándo entres tú. La **única sesión observada** duró **del orden de tres horas**: el turno se ganó
tras ~16 min de barrido posteriores al intento fallido de las `13:50` sobre el ID en EUR, y el
arrendamiento expiró a las **17:00 Madrid** (§«Al desconectar un canal, Channex borra el hilo de
mensajes…»). Eso es una observación con **n=1**, no una asignación garantizada: nadie la ha medido
dos veces, y de las dos marcas horarias que la acotan una (`13:50`) no lleva zona horaria. Tomar
«unas tres horas» como la ventana que te toca sería repetir exactamente el error que este
documento corrige.

**Consecuencia práctica, y es la mitigación**: crear **un rate plan por moneda** (EUR, GBP, USD,
JPY) en la propiedad de staging. El mapeo exige que la moneda del rate plan coincida con la del
hotel de test, así que con un único plan en EUR **solo uno de los ocho hoteles es utilizable** y
la prueba end-to-end depende de ganar una carrera por un recurso concreto. Con los cuatro planes
sirve el primero que se libere. `scripts/channex_bootstrap.py` los crea.

**Consecuencia para la planificación**: ADR 0006 presenta el acceso al entorno de test de
Booking.com como la ventaja decisiva de Channex sobre Beds24, y lo sigue siendo — pero es una
capacidad **contendida y sin garantía de disponibilidad**, no un sandbox propio. Ni el ADR ni la
documentación de Channex lo mencionan. Cualquier plan que dependa de ejercitar una OTA real
tiene que contar con esperas de horas.

| Hotel ID | Moneda | Nota |
|---|---|---|
| `4372137` | **EUR** | **el único que sirve** con un rate plan en euros |
| `5868189`, `6519420`, `10745030`, `11140466` | GBP | |
| `10484818` | JPY | |
| `10485037`, `12152494` | USD | `12152494` exige tarjeta real |

La moneda **tiene que coincidir** con la del rate plan: *"Make sure your rate plans are in the
same currency or you will not be able to map"*. Con el sandbox en EUR, coger el ID que se libere
antes no adelanta nada — el mapeo fallará.

Pasos:

1. Panel → propiedad → **Channels** → Booking.com, `Hotel ID` = `4372137`, `Currency: Auto`.
   **Test Connection** hasta que pase.
2. **Mapping**: su habitación ↔ `Apartamento completo (test)`, su tarifa ↔ `Tarifa estándar
   (test)`. *"Channel wont be activated unless you map rooms and rates"* — sin mapeo el canal
   queda inactivo y no llega nada.
3. Reservar en `https://secure.booking.com/book.html?hotel_id=4372137&test=1` con la tarjeta de
   test `4111-1111-1111-1111`, CVC `123`, caducidad futura.

Verificación: `GET /channels` pasa de 0 a 1 con `is_active: true`, y la reserva aparece en
`GET /bookings` con el `property_id` del sandbox y `channel_id` **poblado** — eso último es lo
que distingue una reserva que ha pasado por la OTA de una creada por la API de CRS.

**Los hoteles de test son compartidos**: pueden aparecer reservas de otros integradores. Es
ruido en los fixtures, no un problema.

---

## Hallazgos medidos

Todo lo de esta sección se midió contra la API real. Donde contradice a ADR 0006 o al PRD se
**anota aquí y no se edita el original**, según la convención de
[ADR 0005](adr/0005-global-email-uniqueness.md).

### El sync no ve modificaciones ni cancelaciones

`GET /bookings` filtra por `arrival_date`, `departure_date` e `inserted_at`. **No hay filtro por
fecha de modificación.** Así que `list_reservations(since)` ve reservas *creadas* después de
`since` y **no** ve que una anterior se haya modificado o cancelado.

No es un bug del adapter: es la consecuencia de elegir `/bookings` sobre el feed de revisions, y
se eligió a propósito (design D1) porque el feed exige `ack` en menos de 30 minutos —
convertiría una lectura en escritura destructiva y haría el sync no repetible. Sirve para
validar el backend, **no sirve como base de un sync de producción**.

**Entrada de diseño directa para `pms-beds24-adapter`**: cualquier proveedor cuya API no ofrezca
filtro por modificación necesita otra arquitectura de sync, no un `since` más fino.

### El filtro temporal ignora la zona horaria que le mandes

`inserted_at` es UTC serializado **sin zona**. Y el filtro compara el reloj de pared literal:

| `filter[inserted_at][gte]` | filas devueltas |
|---|---|
| `2026-08-03T09:00:00` | 2 |
| `2026-08-03T09:00:00Z` | 2 |
| `2026-08-03T11:00:00+02:00` | **0** |

Las tres nombran el mismo instante (las reservas se insertaron a las 09:53 UTC). La tercera
devuelve cero porque Channex **descarta el `+02:00`**. Mandar un ISO tz-aware desde Madrid en
verano abre un **agujero de dos horas** en cada sync, sin error y sin rastro en la
documentación. El adapter convierte a UTC y serializa sin offset.

### `ota_commission` no distingue «cero» de «sin dato», y la OTA no lo arregla

Nunca llega `null`: siempre es un string, y **`"0.00"` cuando no hay dato**. Una reserva creada
*sin* comisión vuelve como `"0.00"`, idéntica a una con comisión real de cero.

El primer arreglo fue una allowlist: respetar el valor si la OTA es de las que la documentación
dice que Channex informa (Booking.com, Airbnb) y devolver `None` en el resto. **Duró hasta que
llegó una reserva real de Booking.com**: `BDC-6558139322` trae `ota_commission: "0.00"`, y
Booking.com siempre cobra comisión. La allowlist no resolvía la ambigüedad, la movía de sitio.

Regla definitiva: **cero significa desconocido, para cualquier OTA**. Se pierde el cero legítimo
—raro— a cambio de no afirmar nunca en falso. `None` dice «no lo sabemos», que es verdad; `0`
sería una afirmación, y R2.4 prohíbe esa afirmación.

### Una reserva real de OTA no se parece del todo a una de CRS

Comparando `BDC-6558139322` (llegada de Booking.com por el canal) con las sembradas por la API
de CRS:

| Campo | CRS | OTA real |
|---|---|---|
| `channel_id` | `null` | **poblado** — es el marcador que las distingue |
| `ota_name` | lo que tú pongas | **`BookingCom`**, sin punto |
| `acknowledge_status` | ausente del feed | `pending` |
| `payment_collect` / `payment_type` | lo que envíes | `property` / `credit_card` |
| `amount` | el que envías | incluye los suplementos del hotel de test |

**`ota_name` es `BookingCom`, no `Booking.com`.** El valor que yo había usado al sembrar era el
segundo, así que sin mapear las dos grafías el canal real habría caído en `OTHER`.

Y el `amount` de `£834.69` para 3 noches no es la tarifa que empujamos (120 GBP/noche): el hotel
de test añade **cuatro suplementos idénticos de €175,45** (servicio, limpieza, electricidad, ropa
de cama) que salen de su propia configuración de impuestos — se ven en
`channel.settings.tax_settings.property_charges`, con `BEDLINEN` entre ellos. Son datos dummy del
hotel compartido, no un fallo del push de ARI.

### ⚠️ Al desconectar un canal, Channex borra el hilo de mensajes y la procedencia de las reservas

Observado cuando expiró el arrendamiento del hotel de test compartido (17:00 Madrid). Channex
eliminó el canal, y con él:

| Recurso | Antes | Después |
|---|---|---|
| `/channels` | 1, activo | **0** |
| `BDC-6558139322` → `channel_id` | poblado | **`null`** |
| `/message_threads` | 1 (con su mensaje) | **0** |
| `/booking_revisions` | 3 | 3 — sobreviven |
| `/bookings` | 3 | 3 — sobreviven |
| `/properties` | 1 | 1 — sobrevive |

Dos consecuencias, y la segunda es la que importa para el negocio:

**1. `channel_id` no es un marcador durable de procedencia.** Es lo que distingue una reserva
llegada de una OTA de una creada por la API de CRS — y **se borra** cuando el canal desaparece.
Cualquier lógica que clasifique el origen de una reserva por ese campo clasificará mal todo el
histórico en cuanto se desconecte el canal. Los fixtures de este change conservan el valor porque
se capturaron a tiempo; el test que buscaba la reserva real *por* `channel_id` se cambió a
buscarla por `ota_name`.

**2. El historial de mensajes se pierde al desconectar.** El hilo con su mensaje desapareció por
completo: no quedó vacío, dejó de existir. Y esto **muerde de lleno en la decisión 2 de
ADR 0006**, que planifica migrar de Beds24 a Channex al llegar a 25–50 unidades y admite que
«durante semanas habrá viviendas en Beds24 y viviendas en Channex». Si desconectar un canal
destruye las conversaciones con los huéspedes, la ventana de migración no es solo una molestia
operativa: **es pérdida de datos**. Cualquier plan de migración tiene que exportar la mensajería
antes de desconectar nada, y `messaging-ai` no puede tratar a Channex como el archivo de las
conversaciones.

### Evidencia del sync end-to-end (R5.1, R5.2)

Ejecutado el 2026-08-03 contra la **API real**, sin mocks y con red:

```
$ pms_sync 5327dad1-f102-4c13-9027-45e5fc6ecc8d 400 --provider channex
pms-sync: created 3, updated 0, skipped 0
```

Y sin el flag, el mismo comando sigue usando `MockPMSAdapter` — reporta las cuatro filas del
mock como saltadas porque este tenant no tiene la propiedad `PMS-REDES11`, que es exactamente la
prueba de que R3.1 se cumple por construcción.

Lo que quedó en la base de datos, con **cada decisión de mapeo verificada sobre datos reales**:

| `external_pms_id` | canal | status | importe | comisión |
|---|---|---|---|---|
| `BDC-6558139322` — **reserva real de Booking.com** | `BOOKING` ← `BookingCom` | `CONFIRMED` ← `new` | 834.69 GBP | **`None`** ← `"0.00"` |
| `OFL-AUTOHOST-TEST-OFFLINE-001` | `MANUAL` ← `Offline` | `CONFIRMED` | 360.00 EUR | `None` |
| `BDC-AUTOHOST-TEST-BDC-001` | `BOOKING` ← `Booking.com` | `CONFIRMED` | 360.00 EUR | **`54.00`** |

Más **3 `TimelineEvent`** de tipo `RESERVATION_IMPORTED` con actor `SYSTEM` —la primera
persistencia de timeline del proyecto alimentada por un PMS real— y **2 `Guest`** para tres
reservas, porque las dos sembradas comparten huésped y la deduplicación por email funcionó.

Las cuatro traducciones que este change decidió, confirmadas en la fila que las ejercita:
`new` → `CONFIRMED`, `BookingCom` → `BOOKING`, `Offline` → `MANUAL`, y un `"0.00"` de
Booking.com → `None` mientras un `54.00` legítimo se conserva.

**Cableado previo** (tarea 6.1): tenant `5327dad1-…` y propiedad `CHANNEX-SANDBOX` con
`pms_external_id = 7963f1e3-…` (el UUID de la propiedad en Channex), creados con los modelos del
dominio. No se tocó `app/cli/bootstrap.py` ni se añadió migración: es una propiedad de un
proveedor que no es el del MVP.

### Límite de tasa: **no medido**, con una observación acotada

Channex no publica límite de tasa, y **no se ha buscado su techo**. Averiguarlo exige
provocárselo, y este documento sostiene lo contrario en el mismo párrafo donde limita el script
de adquisición: *la ausencia de un límite documentado no es permiso para machacarlo*. Así que
esto **no es una medición del límite**, es lo que se observó haciendo otra cosa:

| Observación | Valor |
|---|---|
| Peticiones `POST /channels` del script de adquisición antes de ganar | ~**1.350** (193 barridos × 7 candidatos) |
| Ventana | ~**16 minutos** (barrido cada 5 s) |
| Respuestas `429` | **cero** |
| Cabecera tipo `X-RateLimit-*` | ninguna observada |

Es decir: ~1,4 req/s sostenidos durante un cuarto de hora no tocaron techo ni provocaron
throttling. **No concluir de aquí que no haya límite** — solo que está por encima de eso, y que
un `429` no llegó a verse nunca durante todo el change.

Para `pms-beds24-adapter` esto no se extrapola: Beds24 sí publica su modelo —créditos con coste
dinámico, 100 por 5 minutos y **por cuenta**— y es de otra naturaleza.

### Latencia OTA → Channex: por debajo del minuto

Medido el 2026-08-03: la reserva **no estaba** en `GET /bookings` a las 13:19:05 UTC y su
`inserted_at` es **13:19:39**. La confirmación en Booking.com fue segundos antes de la primera
comprobación, así que el retardo es **≲1 minuto**, del mismo orden que el ~1 minuto que ADR 0006
documenta para los webhooks de Beds24. Es una medición única, no una distribución.

### El feed de revisions **no es durable**, y son dos colecciones distintas

Hay dos endpoints y hacen cosas diferentes:

| Endpoint | Contenido observado |
|---|---|
| `GET /booking_revisions` | **todas** las revisions — 3: dos de CRS y la de OTA |
| `GET /booking_revisions/feed` | solo las **pendientes de acuse** — 1, la de OTA |

Y aquí está el hallazgo que importa, **medido con reloj sobre la reserva real** y no inferido:

| Hora (UTC) | Feed | `acknowledge_status` de la reserva |
|---|---|---|
| 13:19:39 | la revision entra | `pending` |
| 13:31:17 | 1 entrada | `pending` |
| ~13:46 | 1 entrada | `pending` |
| **14:13:44** | **0 entradas** | **`pending`** |

**Nadie llamó a `ack` en ningún momento.** La revision sigue existiendo en
`/booking_revisions` (3 en total); lo que desapareció fue su presencia en el feed. La ventana de
desaparición queda acotada entre **27 y 54 minutos** desde la inserción, lo que encaja con que el
límite de 30 minutos que la documentación presenta como «confirma antes de 30 min o recibirás
avisos por correo» sea en realidad un **TTL duro**: pasado ese tiempo la entrada se va del feed,
la hayas procesado o no.

Peor: en ese estado Channex afirma **tres cosas incompatibles a la vez**.

| Señal | Dice |
|---|---|
| `acknowledge_status` | `pending` — la revision espera confirmación |
| `has_unacked_revisions` | `false` — no hay nada pendiente |
| `/booking_revisions/feed` | vacío — no hay nada que procesar |

Un consumidor que se fíe de `acknowledge_status` sigue esperando algo que ya no puede leer; uno
que se fíe del feed cree que no hay trabajo; uno que se fíe de `has_unacked_revisions` cree que
está al día. **Ninguna de las tres señales basta por sí sola, y no coinciden.**

**Consecuencia directa, y es grave**: un PMS que consulte el feed cada pocas horas —la cadencia
que la documentación de Beds24 recomienda para su propio sync— **perdería revisions en silencio**.
Cualquier diseño que trate el feed como cola durable («leo, proceso, confirmo, y hasta que
confirme sigue ahí») está equivocado. Es entrada de diseño directa para
`reservations-webhooks`, que iba a construirse exactamente sobre esa suposición.

Refuerza además la decisión D1 de leer `/bookings`, aunque por un motivo distinto del que se
escribió: no es solo que consumir el feed obligue a una escritura destructiva, es que **el feed
tampoco garantiza que la entrada te espere**.

Detalle de formato: el `system_id` de una revision de OTA es corto (`859f8ee5`), el de una creada
por CRS es un UUID completo (`cb0221d1-…`). No asumir formato.

### «Resend the latest revision» no produce nada observable por API

El panel ofrece reenviar la última revision. Se probó: el feed conserva la misma entrada, el
mismo `system_id` y la misma `inserted_at`, y no aparece ninguna revision nueva. El reenvío
re-entrega por **webhook**, que es un canal que este change no recibe a propósito.

Consecuencia práctica: **medir el comportamiento de reenvíos y de orden de entrega exige un
receptor de webhooks**, y montarlo aquí sería mala idea — el payload lleva `card_number`, `cvv` y
`expiration_date`, así que apuntarlo a un capturador de terceros para medir latencia es un
intercambio inaceptable. Queda para `reservations-webhooks`, con su propio endpoint bajo la
regla 12.

### ⚠️ Sin verificar: la estabilidad de `unique_id` entre revisions

**La suposición más cargada del change, y no se ha podido comprobar.**

`external_pms_id ← unique_id` es lo que sostiene la idempotencia de `ReservationIngestor`. La
documentación dice que `unique_id` es estable entre revisions y que `system_id` es por revision,
y todo el mapeo se apoya en eso. Lo que **no** se ha observado nunca es una reserva con **dos**
revisions: cada una de las tres tiene exactamente una.

**Cuatro vías intentadas, las cuatro cerradas**, cada una por un motivo distinto. El negativo
está documentado con detalle porque ahorra repetirlo:

1. **Modificar fechas en Booking.com** (hotel `5868189`) — la tarifa que quedó mapeada resultó
   *no reembolsable*: «No se pueden cambiar las fechas de estancia».
2. **«Resend the latest revision»** desde el panel — no crea ninguna revision nueva; re-entrega
   por webhook, que es un canal que este change no recibe.
3. **Reservar y cancelar en un segundo hotel** (`10745030`) — Booking.com **rechazó todas las
   tarjetas de test** (`4111…`, `5555…`), así que no llegó a existir reserva. **La causa estaba
   documentada y no la busqué**: la ficha de ese hotel en la guía de Channex lleva el aviso
   `Bookings not possible currently for this ID`. Yo solo había leído la lista resumen que
   muestra el formulario *Create Channel*, que **no** incluye ese aviso. Una versión anterior de
   este documento concluía que «la anotación de Channex está incompleta» — era falso: la
   información existía, en la ficha por hotel. Leerla antes de gastar un turno.
4. **Re-enviar por la API de CRS** el mismo `ota_reservation_code` con fechas distintas —
   rechazado con `422 {"ota_reservation_code": ["already exists"]}`. La Booking CRS API es de
   **creación únicamente**: no ofrece camino a una modificación, así que no se puede fabricar
   una segunda revision sin pasar por una OTA.

Una cancelación **sí** valdría (genera una revision con `status: cancelled` sobre la misma
reserva, que es la comparación que hace falta), pero exige una reserva viva sobre un hotel que
acepte tarjeta de test.

**Qué debe hacer `pms-beds24-adapter` antes de construir deduplicación encima**: provocar una
modificación real (tarifa flexible, o el equivalente en Beds24) y verificar que `unique_id` no se
mueve mientras `revision_id`/`system_id` sí. Si se moviera, cada modificación crearía una reserva
nueva en vez de actualizar la existente.

### La API de canales sí existe, pero el mapeo no

`POST /channels` funciona con una key normal —valida por campo y devuelve 422—, así que
*"Access to the channel API is only for Whitelabel accounts"* es **falso** para crear canales. El
código del canal es `BookingCom` y el hotel va en `settings: {"hotel_id": "..."}`.

Dos trampas que cuestan un rato descubrir:

1. **`property_id` en el `POST` se ignora en silencio.** El canal se crea con `properties: []`,
   o sea fuera de la propiedad: invisible en el panel y no mapeable. La vinculación es un `PUT`
   aparte y `properties` es un **array plano de UUIDs** — con objetos devuelve 500.
2. **El mapeo no se puede hacer por API.** El `PUT` con `rate_plans` responde 200 y deja el array
   vacío, porque un mapeo necesita los ids del lado de Booking.com (`room_type_code`,
   `rate_plan_code`) y **ningún endpoint los expone**. Solo la pestaña Mapping los trae, en vivo.
   Aquí la documentación acierta en la práctica aunque yerre en el motivo.

`scripts/channex_claim_test_hotel.py` automatiza la adquisición: recorre los hoteles en orden de
vencimiento, detecta la contención por el `422` y para al ganar. Adquirió `5868189` **6 segundos**
después de liberarse, tras 193 barridos de espera — que es la prueba de que a mano no se llega.

### El vocabulario de estado no es el nuestro

Channex usa `new`, `modified`, `cancelled`. Ninguno existe en `ReservationStatus`, y
`parse_ingested` **lanza** ante un valor desconocido, que el ingestor convierte en fila saltada.
**Sin traducción explícita el sync importaría cero reservas informando cada una como error.**

Traducción: `new`/`modified` → `CONFIRMED`, `cancelled` → `CANCELLED`. `new` va a `CONFIRMED`
porque una reserva que llega de un feed de PMS es un booking que alguien ya aceptó — el
argumento está escrito en el docstring de `parse_ingested`.

**Asimetría deliberada**: un canal desconocido va a `OTHER` para no perder la reserva; un
**status** desconocido se deja fallar. Un canal mal puesto no mueve nada; un status mal puesto
conduce la `PropertyStateMachine`.

### Paginación: `limit` 10 por defecto, y orden distinto por colección

`meta` trae `{total, page, limit, order_by, order_direction}`. El `limit` por defecto es **10**,
así que paginar no es opcional: sin ello todo sync ve como mucho diez reservas.

- `/bookings` → `order_by: inserted_at`, `order_direction: **desc**`
- `/booking_revisions/feed` → `order_by: inserted_at`, `order_direction: **asc**`

Con orden descendente y paginación por offset, una reserva que entre a mitad del recorrido
**desplaza filas entre páginas**. Es inestabilidad clásica de offset y afecta a cualquier sync
por páginas.

**Y `meta.limit` no es de fiar como señal de última página**: muchas APIs REST devuelven ahí el
`?limit=` que pediste. El cliente solo lo cree cuando **difiere** de lo solicitado; si coincide,
pagina hasta encontrar una página vacía.

### Identidad: `unique_id`, y `system_id` solo en revisions

`/bookings` expone `unique_id`, `booking_id`, `revision_id`, `id` — **no `system_id`**, que sí
está en `/booking_revisions`, donde efectivamente es por revision. `unique_id` combina el código
de OTA con el de reserva (`BDC-…`, `OFL-…`) y es estable entre revisions: es lo que sostiene la
idempotencia por `(tenant_id, external_pms_id)`.

### Webhooks: confirmado lo que ADR 0006 afirmaba, con un matiz

Sin firma criptográfica; la recomendación es una cabecera de secreto compartido propia.
Reintentos con backoff exponencial hasta 10 intentos. Y literal: *«Sequence of incoming webhook
calls can be different from sequence of events which trigger that calls»*, con la instrucción
explícita de tratar el webhook como disparador y releer por API.

**El matiz, y desvía de ADR 0006**: Channex **sí tiene API para configurar webhooks**, incluido
`is_global: true` con `property_id: null`, a diferencia de Beds24, cuya configuración es manual
por propiedad desde su panel.

Todo esto es alcance de `reservations-webhooks` y de la **regla 12** de
`sdd/steering/security.md`. Este change no expone ninguna ruta entrante.

### `raw_message` no se versiona

El payload trae el mensaje original de la OTA en `raw_message`. El anonimizador del script de
captura **lo borra siempre**, y debe seguir haciéndolo: es texto libre y el sitio más probable
donde se esconda un nombre o un teléfono de huésped.

---

## Lo que queda por medir en Beds24 y no se extrapola de aquí

Para que `pms-beds24-spike` arranque con la lista cerrada:

1. **`X-RequestCost` por endpoint y por forma de petición.** Beds24 factura en créditos con
   coste **dinámico y no publicado**, 100 por 5 minutos y **por cuenta**. Channex no tiene nada
   equivalente, así que el presupuesto de créditos —del que depende la cadencia del scheduler de
   `celery-jobs`— no se puede estimar desde aquí.
2. **Latencia real de sus webhooks**, documentada como ~1 minuto de media.
3. **Payloads reales de reserva y de mensaje de Beds24.** Los nombres de campo de Channex no
   dicen nada de los de Beds24: este change demuestra precisamente que la documentación de un
   proveedor no predice su payload.
4. **Su límite de tasa**, que aquí no se llegó a medir por falta de volumen — un sandbox con dos
   reservas no lo provoca.

---

## Referencias

- [ADR 0006 — proveedor PMS/Channel Manager](adr/0006-pms-channel-manager-provider.md)
- `sdd/specs/reservations.md` — el puerto `PMSAdapter` y el CLI de sync
- `sdd/changes/channex-staging-adapter/design.md` — decisiones D1–D11 y §D7 bis
- [Documentación de Channex](https://docs.channex.io/)
