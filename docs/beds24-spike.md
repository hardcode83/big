# Beds24 — runbook de medición y hallazgos

Cómo se opera la cuenta de desarrollo de Beds24 y **qué se midió con ella**. Este documento es
el entregable del change `pms-beds24-spike`: no hay código de producto en él, la salida es la
entrada de diseño de `celery-jobs`, `reservations-webhooks` y `pms-beds24-adapter`.

[ADR 0006](adr/0006-pms-channel-manager-provider.md) elige Beds24 como proveedor del MVP y deja
tres cosas explícitamente sin resolver porque no se pueden resolver leyendo documentación: el
coste real en créditos por petición, la latencia real de los webhooks y la forma real de los
payloads. `channex-staging-adapter` cerró la lista y dejó dicho que **no se extrapola**
(`channex-staging.md` §«Lo que queda por medir en Beds24»). Esto la resuelve.

> **Estado (2026-08-04): cuenta abierta, paso 0 hecho, mediciones en curso.**
> La cuenta de desarrollo existe (una propiedad `TEST-MEDICION`, id 345754, room 713992, sin
> canales). El paso 0 corrigió dos supuestos y tumbó un tercero. Las mediciones de coste están
> empezadas; lo que sigue marcado *no medido* abajo es lo que aún falta.

---

## ⚠️ Regla dura: qué no se conecta nunca

**La cuenta de desarrollo de Beds24 no lleva ningún canal OTA conectado. Ninguno.**

No es prudencia genérica, es la misma lección que `channex-staging.md` documenta y que aquí
tiene una vuelta de tuerca: Beds24 **sí** es el proveedor del MVP, así que la tentación de
«ya que estamos, conecto los pisos reales» es mucho mayor que con Channex. No se hace en este
change. REDES11 y PAJARITOS8 están vendiendo, Airbnb admite **un único channel manager por
cuenta**, y conectar y desconectar deja una ventana de corte sobre dos anuncios vivos.

Conectar canales es alcance de `pms-beds24-adapter`, con su propia planificación de la
ventana de corte. Aquí se mide contra una cuenta vacía, con reservas creadas por API.

La consecuencia buena de esa regla: sin canales OTA, los payloads capturados no traen datos de
titular de tarjeta reales. Eso **no** relaja nada — la regla 13 de `steering/security.md` no
depende de la probabilidad, y tanto la captura de fixtures como el receptor de webhooks
descartan lo que tenga forma de tarjeta antes de escribir a disco.

---

## Alta de la cuenta

**El reloj empieza al registrarse.** Trial de 14 días, ~€15,50/mes después. Ese es el motivo de
que este change exista separado de `channex-staging-adapter` y de que el banco de medición se
construyera **antes** de abrir la cuenta: los 14 días van íntegros a medir, no a escribir
herramientas.

Antes de registrarte, ten listo:

- El banco corriendo en local (secciones 1-6 del change, ya commiteadas).
- `cloudflared` instalado, para el túnel efímero de la medición de webhooks.
- Una hora seguida: la medición de webhooks necesita provocar hechos y esperarlos.

> ⚠️ **Escribe siempre bajo `/app/`, nunca bajo `/tmp/`.** `docker compose run --rm` destruye
> el contenedor al terminar, así que un fichero en `/tmp` del contenedor desaparece con él y el
> `report` no encuentra nada. `./backend` está montado en `/app`, de modo que `--out=/app/x.jsonl`
> aterriza en `backend/x.jsonl` de tu repo y sobrevive.

### Paso 0 — confirmar los supuestos antes de gastar un solo crédito

El banco se escribió sin cuenta, así que lleva **supuestos marcados como `ASSUMPTION`** en el
código. Confírmalos contra la especificación OpenAPI 3.0 publicada de la API V2 **antes** de la
primera llamada autenticada, porque uno de ellos decide a qué host se manda la credencial:

**Tres ya están resueltos** contra la documentación pública (2026-08-04), sin gastar créditos:

| Supuesto | Estado |
|---|---|
| Host y base de la API | ✅ **`https://beds24.com/api/v2`**. No existe subdominio `api.`; era una conjetura y se ha retirado del allowlist. |
| Flujo de token | ✅ Invite code → `GET /authentication/setup` con cabecera `code` → refresh token. Luego `GET /authentication/token` con cabecera `refreshToken` → access token de 24 h, que viaja en cabecera `token`. La respuesta trae `token`, `expiresIn` y `refreshToken`. El código ya lo hacía así. |
| Ruta de escritura | ✅ `POST /bookings`, con sobre de respuesta que lleva `modified`, `errors`, `warnings` e `info`. |
| Cabecera de coste | ✅ **`X-Request-Cost`, con guiones.** La conjetura era `X-RequestCost` y no casaba con nada: el sondeo habría registrado `null` en todas las mediciones y el informe habría dicho «cadencia no calculable» sin error visible. Acompañan `X-Five-Min-Limit-Remaining` (decimal) y `X-Five-Min-Limit-Resets-In` (segundos). |
| Canales en `/properties` | ⛔ **No existen.** No hay ningún campo de canales en la respuesta, ni con `includeAllRooms=true`. El guardia anti-escritura se rediseñó por eso: ahora cuenta propiedades en vez de detectar canales. |

Los que siguen abiertos exigen la cuenta delante:

| Supuesto | Dónde | Qué comprobar |
|---|---|---|
| Rutas del catálogo | `beds24_probe.py` → `CATALOGUE` | Que `/bookings`, `/properties` y `/inventory/rooms/calendar` existan y sean las que el sync usará. |
| Claves de identidad y de tiempo | `beds24_webhook_sink.py` → `BOOKING_REF_KEYS`, `EVENT_TIME_KEYS` | Qué clave lleva el id de reserva y cuál el instante del hecho. |
| **Escritura de reservas** | `beds24_probe.py` → `BOOKINGS_WRITE_PATH`, los cuerpos de `provoke`, y `_extract_booking_ref` | **El más importante de la tabla**, porque es el único cuyo fallo cuesta una escritura. Confirma la ruta, la forma del cuerpo y —sobre todo— **cómo devuelve el id la respuesta de creación**: si el script no lo reconoce, aborta y te deja una reserva confirmada que hay que borrar a mano. |

Si alguno falla el arreglo es de una línea, pero descubrirlo a mitad de la ventana de medición
cuesta créditos y tiempo del trial.

### Credencial

Beds24 usa su **API V2** (REST, OpenAPI 3.0). El flujo, confirmado en el paso 0, tiene tres
piezas con vidas muy distintas:

| Pieza | Vida | Notas |
|---|---|---|
| **Invite code** | **24 h**, y se canjea **una sola vez** | Se genera en el panel. Es el único paso que no hace ningún script. |
| **Refresh token** | Indefinida **mientras se use**; muere a los **30 días sin usar** | Credencial **de cuenta**: da escritura sobre *todas* sus propiedades. |
| **Access token** | `expiresIn` segundos (24 h) | El sondeo lo canjea al arrancar y lo mantiene **solo en memoria**. |

#### 1. Genera el invite code

Panel de Beds24 → página de **API** → *generate invite code*. Marca los scopes y vuelve a
pulsar *generate invite code*.

> ⚠️ **Los scopes se fijan al crear el invite code y no se pueden cambiar después.** Si te
> quedas corto no hay forma de ampliarlos: hay que generar otro invite code y canjearlo por un
> refresh token nuevo. Marca de una vez lectura de **bookings**, **properties** e
> **inventory**, y **escritura de bookings** — sin esta última `provoke` no puede causar los
> eventos que R2.2 necesita, y lo descubrirías a mitad de la ventana de medición.

#### 2. Canjéalo por el refresh token, sin que pase por el historial

El invite code y el refresh token son credenciales, y una línea de comandos con la credencial
dentro sobrevive en `~/.zsh_history`. Es exactamente el descuido que el propio script se niega
a permitir (`_reject_unknown_arguments` rechaza un token pasado por `argv` **sin imprimirlo**),
así que el runbook no va a pedírtelo por otra vía. Lee ambos con `read -rs`, que no hace eco ni
deja rastro:

```bash
read -rs "?Invite code: " BEDS24_INVITE_CODE

RESPONSE=$(curl -sS -w '\n%{http_code}' \
  -H "code: $BEDS24_INVITE_CODE" \
  https://beds24.com/api/v2/authentication/setup)
unset BEDS24_INVITE_CODE

[ "$(printf '%s' "$RESPONSE" | tail -1)" = "200" ] \
  && printf '%s' "$RESPONSE" | sed '$d' | python3 -c 'import sys,json; d=json.load(sys.stdin); print("refreshToken:", d["refreshToken"]); print("expiresIn:", d.get("expiresIn"))' \
  || { echo "FALLÓ — invite code caducado, ya canjeado, o scopes mal:"; printf '%s' "$RESPONSE" | sed '$d'; }
```

Guarda el `refreshToken` en tu gestor de contraseñas. Después, en cada sesión de medición:

```bash
read -rs "?BEDS24_REFRESH_TOKEN: " BEDS24_REFRESH_TOKEN && export BEDS24_REFRESH_TOKEN
```

(En bash la sintaxis del prompt es `read -rsp "BEDS24_REFRESH_TOKEN: " BEDS24_REFRESH_TOKEN`.)

#### 2 bis. Scopes: pide el mínimo, no `all:*`

El primer invite code de este proyecto se generó con **todo** marcado, y `/authentication/details`
lo delata:

```
scopes: all:bookings, all:bookings-personal, all:bookings-financial,
        all:inventory, all:properties, all:accounts, all:channels
```

Dos de esos no deberían estar. **`all:channels` concede conectar y desconectar canales OTA** —
justo lo que R6.1 prohíbe en esta cuenta, y el poder que convertiría un token filtrado en un
incidente sobre REDES11 y PAJARITOS8 el día que la cuenta deje de estar vacía. `all:accounts` no
lo usa nada de este banco.

Lo que el banco necesita de verdad:

| Scope | Para qué | ¿Hace falta? |
|---|---|---|
| bookings (lectura **y escritura**) | `/bookings`, y `provoke` para causar los eventos de R2 | **Sí** |
| properties (lectura) | el guardia de cuenta, y la escritura del webhook | **Sí** (escritura solo si configuras webhooks por API) |
| inventory (lectura) | `/inventory/rooms/calendar` | **Sí** |
| bookings-personal / bookings-financial | datos de huésped e importes en el payload | Sí, si quieres fixtures representativos |
| **channels** | conectar/desconectar OTAs | **NO. Nunca en esta cuenta.** |
| **accounts** | administración de la cuenta | **NO** |

#### 2 ter. Whitelist de IP

`/authentication/details` muestra también `whiteListOnly: false` y `whiteList: [""]`. Beds24
permite **restringir el token a una lista de IPs**, y está sin usar. Para una credencial de
cuenta con escritura es una capa gratis: si mides siempre desde el mismo sitio, actívala.

No la dejes puesta si vas a medir desde una IP cambiante (casa/oficina/VPN), porque el fallo se
manifiesta como un 401 que se confunde con «token caducado».

---

## Rotar el refresh token

**Un refresh token no genera otro.** Solo produce access tokens. Un refresh token nuevo nace
únicamente de un **invite code**, y el invite code se genera en el panel: es el único paso de
todo el flujo que exige una persona, y no hay forma de automatizarlo desde la API.

Consecuencia práctica: **rotar no es un comando, es un procedimiento.** Este:

1. **Genera un invite code nuevo** en Settings → Marketplace → API, con los scopes mínimos de
   arriba (no `all:*`) y un `deviceName` que diga de qué es — el actual pone `autohostai-dev`,
   que se lee bien en `/authentication/details`.
2. **Canjéalo** (24 h de validez, un solo uso):

   ```bash
   read -rs "?Invite code: " C; echo
   curl -sS -H "code: $C" https://beds24.com/api/v2/authentication/setup
   unset C
   ```

3. **Verifica el nuevo antes de tirar el viejo**, que es el paso que la gente se salta:

   ```bash
   read -rs "?refreshToken nuevo: " R
   T=$(curl -sS -H "refreshToken: $R" https://beds24.com/api/v2/authentication/token \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
   curl -sS -H "token: $T" https://beds24.com/api/v2/authentication/details \
       | python3 -m json.tool
   ```

   Comprueba en la salida que `validToken` es `true` y que **los scopes son los que pediste**.
   Si te quedaste corto, no hay ampliación posible: vuelta al paso 1.

4. **Guarda el nuevo** en el gestor de contraseñas y sustituye el viejo.
5. **Revoca el viejo.** La documentación de Beds24 afirma que la API soporta revocación, pero no
   he verificado la ruta y **no conviene adivinarla** — llamar a ciegas a algo que suene a
   revoke puede matar el token que estás usando. Búscala en el Swagger de
   `https://beds24.com/api/v2/`, o revócalo desde la página de API del panel si hay control para
   ello.
6. **Si no encuentras cómo revocar**, el viejo muere solo **a los 30 días sin usarse**. Es la
   red de seguridad, no el plan: son 30 días de una credencial con escritura sobre la cuenta.

### Cuándo rotar

- **Siempre** que el valor haya aparecido en un sitio que no sea el gestor de contraseñas: un
  historial de shell, un log, un ticket, una conversación.
- **Antes** de que la cuenta pase a tener algo que valga — en particular, antes de conectar
  cualquier canal OTA.
- Cuando los scopes sean más amplios de lo que el consumidor necesita, como es el caso hoy.
- Al cerrar el spike, si el token se creó solo para medir.

### Qué NO cuenta como rotar

Generar un invite code nuevo **no invalida por sí solo los refresh tokens anteriores**. No lo he
verificado, y asumir que sí es el error que deja dos credenciales vivas donde creías tener una.
Rotar es sustituir *y* revocar.

---

#### 3. Comprueba que funciona antes de seguir

Una llamada barata que confirma el canje y, de paso, resuelve el supuesto de la forma de
`/properties` del que depende el guardia de canales:

```bash
TOKEN=$(curl -sS -H "refreshToken: $BEDS24_REFRESH_TOKEN" \
  https://beds24.com/api/v2/authentication/token \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

curl -sS -H "token: $TOKEN" 'https://beds24.com/api/v2/properties?includeAllRooms=true' \
  | python3 -m json.tool | head -60
```

Si `TOKEN` sale vacío, el refresh token está mal o los scopes no llegan. Si la respuesta trae
propiedades, mira **bajo qué clave aparecen los canales**: ese nombre es lo que hay que tener
en `_connected_channels`, y hasta que esté el guardia se negará a escribir.

> El `TOKEN` de arriba caduca en 24 h y vive solo en esa shell. No lo guardes en ningún sitio:
> el sondeo lo vuelve a canjear él solo en cada ejecución.

El sondeo lo canjea al arrancar y mantiene el access token **solo en memoria** — no se cachea
en disco, porque un fichero con una credencial viva durante 24 h es superficie que no hace
falta.

> **El refresh token es de cuenta, no de propiedad.** ADR 0006 lo señala y la regla 3 de
> `steering/security.md` lo subraya: una credencial de cuenta concede escritura sobre *todas*
> sus propiedades. Es más peligrosa que una por propiedad, no menos. Vive en el entorno, que es
> el caso que la regla 3 excluye de su obligación de Fernet y que gobierna la regla 8: en
> `.env.example` solo el nombre, nunca un valor.

---

## Medir el coste en créditos

Beds24 factura en créditos con **coste dinámico y no publicado**: 100 por 5 minutos y **por
cuenta**, con el coste de cada llamada calculado según su complejidad. Duplicar el límite
cuesta €10/mes por ticket de soporte. La documentación desaconseja explícitamente el uso en
tiempo real y recomienda sincronización completa cada ~6 h.

Nada de eso dice cuánto cuesta *nuestro* ciclo de sync, y la cadencia del scheduler de
`celery-jobs` es una función de ese número.

```bash
docker compose run --rm --no-deps -e BEDS24_REFRESH_TOKEN backend uv run python scripts/beds24_probe.py probe \
    --out=/app/beds24-cost.jsonl
```

El sondeo recorre un catálogo de peticiones y registra, por cada una, el `X-RequestCost` que
devuelve la cabecera junto a la **forma** de la petición — tamaño de página, amplitud del rango
de fechas, número de propiedades. Cada endpoint se mide con al menos dos formas: es lo único
que distingue un coste fijo de uno proporcional, y esa distinción es la que decide si el sync
puede paginar o tiene que trocear.

Dos cosas que el sondeo hace y conviene saber:

- **Se autolimita.** Ritmo configurable con default conservador, y ante una respuesta de cuota
  agotada para y espera a la siguiente ventana en vez de reintentar. No busca el techo
  provocándolo: agotar la cuota de la cuenta para saber dónde está es romper la cuenta para
  medirla, y el consumo de un ciclo se deriva sumando los costes medidos.
- **Un coste ausente se registra como `null`, nunca como `0`.** Un coste desconocido y un coste
  nulo llevan a presupuestos distintos, y confundirlos es exactamente el error que este
  documento existe para no cometer.

El JSONL crudo se commitea como `beds24-request-cost.jsonl`, al lado de este fichero: el
informe se deriva de datos revisables, no de una transcripción.

```bash
docker compose run --rm --no-deps -e BEDS24_REFRESH_TOKEN backend uv run python scripts/beds24_probe.py report \
    --out=/app/beds24-cost.jsonl
```

renderiza la tabla de coste y la **cadencia máxima sostenible** — el intervalo mínimo entre
syncs por cuenta que se deduce del coste del ciclo contra la ventana de 100 créditos / 5 min.
Esa cifra es la que `celery-jobs` consume.

---

## Medir la latencia de los webhooks

ADR 0006 documenta ~1 minuto de media. Es lo que dice el proveedor; esto lo comprueba.

Beds24 **no tiene API de configuración de webhooks**: se configuran por propiedad desde su
panel. Es un matiz frente a Channex, que sí la tiene, y que `channex-staging-adapter` dejó
anotado. Así que el paso es manual por diseño ajeno, no por pereza nuestra.

**El receptor corre en el host, no en el contenedor.** `beds24_webhook_sink.py` es **solo
biblioteca estándar**, así que arranca con el `python3` del sistema sin Docker ni `uv`. Eso
importa: el sink hace bind a `127.0.0.1` a propósito —mientras dura la medición es un endpoint
**sin autenticar que escribe a disco**, y su única puerta debe ser el túnel efímero— y
`cloudflared` también corre en el host, así que ambos están en el mismo lado y el loopback
funciona. Levantarlo dentro del contenedor obligaría a bindear `0.0.0.0` o a publicar el puerto,
que es justo lo que abre esa superficie.

1. **Terminal 1** — levanta el receptor y déjalo:

   ```bash
   python3 backend/scripts/beds24_webhook_sink.py --out=/tmp/beds24-webhooks.jsonl
   ```

2. **Terminal 2** — el túnel, y copia la URL `https://….trycloudflare.com` que imprime:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:8099
   ```

3. **Terminal 3** — configura esa URL como webhook **por API**, sin tocar el panel (medido:
   `POST /properties` lo escribe):

   La cabecera estática es la **única** autenticación que Beds24 ofrece en lugar de una firma,
   así que la regla 12(a) la trata como credencial y viaja por el entorno, no por `argv`:

   ```bash
   read -rs "?BEDS24_WEBHOOK_SECRET (p. ej. 'X-AutoHost-Probe: 1'): " BEDS24_WEBHOOK_SECRET
   export BEDS24_WEBHOOK_SECRET

   docker compose run --rm --no-deps \
     -e BEDS24_REFRESH_TOKEN -e BEDS24_WEBHOOK_SECRET backend \
     uv run python scripts/beds24_probe.py webhook \
       --url=https://TU-URL.trycloudflare.com/hook \
       --confirm-writes --out=/app/beds24-cost.jsonl
   ```

   No hay flag `--secret=`: el script lo rechaza, y sin echo del valor.
4. Provoca los hechos **con el sondeo**, no a mano:

   ```bash
   docker compose run --rm --no-deps -e BEDS24_REFRESH_TOKEN backend uv run python scripts/beds24_probe.py provoke \
       --room=713992 --confirm-writes --out=/app/beds24-cost.jsonl
   ```

   > ⚠️ **`provoke` es la única subcomanda que escribe.** Por eso exige `--confirm-writes` y,
   > antes de tocar nada, lee `/properties` y verifica que **la cuenta tiene exactamente una
   > propiedad** y que el room que le pasas pertenece a ella. Beds24 no tiene entorno de
   > staging, así que ese chequeo hace aquí el papel que en Channex hacía el default apuntando
   > a staging: lo único que separa una medición de escribir en una vivienda que vende.
   >
   > **Por qué cuenta propiedades en vez de detectar canales.** R6.1 está escrito en términos
   > de canales OTA conectados y así se implementó primero. Medido el 2026-08-04: `/properties`
   > **no expone ningún campo de canales**, ni con `includeAllRooms=true`. Un chequeo que falla
   > cerrado sobre un campo ausente se niega siempre, y uno que falla abierto no protege nada.
   > Contar propiedades ataca el mismo riesgo de forma más directa: lo que pone en peligro
   > REDES11 y PAJARITOS8 es apuntar el script a la **cuenta equivocada**, y la de medición
   > tiene una propiedad mientras la real tiene dos.
   >
   > Si aborta diciendo que la cuenta tiene más de una propiedad, **no insistas**: mira a qué
   > cuenta pertenece tu `BEDS24_REFRESH_TOKEN`.
   >
   > `--room=` es el id de una **habitación**, no de la propiedad: Beds24 modela
   > propiedad → roomTypes → units, y la reserva se escribe contra un `roomId`.

   Crea, modifica y cancela una reserva —tres hechos, el mínimo de R2.3— y **anota el
   `booking_ref` de cada uno en el registro de coste**. Ese es el detalle que hace calculable
   la latencia: si provocas los hechos por tu cuenta desde el panel, el registro del sondeo no
   sabe a qué reserva corresponden y todo webhook que no traiga su propio sello temporal se
   quedará sin latencia medida.

La URL del quick tunnel cambia en cada sesión, así que el paso 3 se repite cada vez que se
retoma la medición.

El receptor sella cada petición con el instante UTC de **recepción** — el reloj es nuestro a
propósito: es literalmente la magnitud que se está midiendo, y meter un capturador de terceros
en medio mediría su latencia además de la del proveedor. La latencia sale de restar ese sello
al instante del hecho, tomado del propio payload si lo trae y, si no, de la línea del sondeo
con el mismo `booking_ref`.

**No se publica una media de tres valores como si fuera una distribución.** Se publican los
tres valores.

### Lo que el receptor NO es

No es el endpoint de webhooks del producto. Nuestra API sigue sin exponer ninguna ruta
entrante, y este script no escribe en `webhook_events`.

Construir la ruta de verdad obliga a cumplir entera la regla 12 de `steering/security.md`
—cabecera con valor por tenant comparada en tiempo constante, ruta con token opaco, límite de
tasa, tope de cuerpo, y re-lectura por API encolada y coalescida— y eso es el alcance completo
de `reservations-webhooks`.

El cuerpo y las cabeceras pasan por el mismo anonimizador fail-closed que la captura de
fixtures antes de tocar el disco. De las cabeceras se persiste el **nombre**, nunca el valor:
una de ellas es la credencial estática de autenticación.

---

## Capturar payloads reales

```bash
docker compose run --rm --no-deps -e BEDS24_REFRESH_TOKEN backend uv run python scripts/beds24_probe.py capture bookings messages
```

Los payloads se anonimizan **en el momento de capturar**, no en una pasada posterior: un
fichero que hay que limpiar a mano es un fichero que se commitea con datos reales el día que
alguien tiene prisa.

La política es **fail-closed**: una hoja sobrevive solo si su clave es dato de negocio
reconocido. La allowlist de Beds24 nace incompleta a propósito —los nombres de campo de Channex
no dicen nada de los de Beds24, y este proyecto ya aprendió que la documentación de un
proveedor no predice su payload— así que el bucle es:

1. capturar,
2. abrir el fichero y ver qué salió como `***scrubbed***` sin merecerlo,
3. ensanchar la allowlist en `beds24_probe.py`,
4. recapturar.

Ese bucle es seguro porque el error por omisión es **sobre-anonimizar**, que produce un fixture
menos útil, nunca una filtración. El modo de fallo es visible en vez de silencioso.

---

## Hallazgos medidos

> **Nada de esta sección está medido todavía.** Cada entrada dice *no medido* y se sustituye
> por su valor cuando la cuenta exista. Lo que siga sin medirse se queda marcado como tal —
> mismo contrato que `channex-staging.md`, donde el límite de tasa figura explícitamente como
> no medido en vez de omitirse.

### Coste en créditos por endpoint y forma

**Medido el 2026-08-04**, validando cada ruta y cada forma una por una. Todas las rutas del
catálogo existen y responden 200; lo único que la validación tuvo que corregir fue el formato de
fechas.

**Con registro commiteado** — generado por `beds24_probe.py report` desde
[`beds24-request-cost.jsonl`](beds24-request-cost.jsonl), que es la evidencia que R1.5 exige:

| Endpoint | Forma | `X-Request-Cost` |
|---|---|---|
| `GET /bookings` | `limit=10` | **1** |
| `GET /bookings` | `limit=100` | **1** |
| `GET /bookings` | ventana 1 día | **1** |
| `GET /bookings` | ventana 90 días | **1** |
| `GET /properties` | por defecto | **1** |
| `GET /properties` | `?id=<uno>` | **1** |
| `GET /inventory/rooms/calendar` | ventana 7 días | **1** |
| `GET /inventory/rooms/calendar` | ventana 90 días | **1** |

**Escrituras y capturas, RESPALDADAS desde el 2026-08-06** (re-ejecutadas en
`pms-beds24-adapter`, tarea 1.5). Estaban transcritas a mano y ahora salen del registro:

| Endpoint | Forma | `X-Request-Cost` | Antes decía |
|---|---|---|---|
| `GET /bookings/messages` | captura | **1** | 1 ✔ |
| `POST /bookings` | crear reserva | **1,1** | ~~1~~ ❌ |
| `POST /bookings` | modificar reserva | **1,1** | 1,1 ✔ |
| `POST /bookings` | cancelar reserva | **1,1** | 1,1 ✔ |
| `POST /properties` | escritura de webhooks | 1 | **sigue transcrita** |

> **La transcripción tenía un error, y es exactamente para lo que existía la re-medición.**
> `POST /bookings` creando una reserva se publicó como **1** crédito y cuesta **1,1**: las tres
> escrituras cuestan lo mismo, no dos de tres. El coste fraccionario queda **confirmado con
> registro** en las tres, así que la decisión de parsear el coste como decimal —`int("1.1")`
> lanza, y un coste fraccionario se registraría como *no medido*— ya no descansa sobre una
> observación sin respaldo.
>
> **`POST /properties` sigue sin respaldo a propósito**: escribe la configuración de webhooks de
> la propiedad, y eso pertenece a `beds24-webhook-cutover-measurement`. Re-medirla habría
> cambiado el estado de la cuenta por una fila de una tabla.

> ⚠️ **No concluir de aquí que el coste sea plano.** Esta cuenta está **vacía**: cero reservas y
> una propiedad. Todas las respuestas devolvieron `count` 0 o 1, así que ninguna forma movió
> volumen de datos y el eje que se sospechaba —tamaño de página, amplitud de ventana— no llegó a
> ejercitarse de verdad. Lo que está medido es el **coste base**: pedir 100 elementos no cuesta
> más que pedir 10 **cuando no hay elementos que devolver**. La diferenciación real, si existe,
> aparece con reservas dentro, y eso llega con `provoke`.
>
> Es el mismo tipo de cautela que `channex-staging.md` aplica a su límite de tasa: se publica lo
> observado, no lo que apetecería concluir.

### ⚠️ La ventana de modificación funciona, pero **oculta las cancelaciones** por defecto

**Medido el 2026-08-06** (`pms-beds24-adapter`, tareas 1.2 y 1.3), y es el hallazgo que decidió
la forma del adapter. Cuatro cosas, en orden de importancia:

1. **`modifiedFrom` existe, restringe de verdad y acepta las dos ortografías** — `YYYY-MM-DD` y
   el instante ISO con `Z`, ambas 200 y 1 crédito. Esto es lo que separa a Beds24 de Channex,
   cuyo `/bookings` solo filtra por fecha de creación y por tanto **nunca** ve una cancelación.

2. **El listado por defecto NO devuelve las canceladas.** Ciclo crear → modificar → cancelar con
   `modifiedFrom=t0`: visible, visible, **invisible**. Un adapter que se fiara de la ventana de
   modificación a secas daría por confirmada una estancia cancelada — el mismo fallo que
   creíamos no heredar, alcanzado por otro camino.

3. **`includeCancelled=true` se ignora en silencio.** Devuelve `200` y no cambia nada. Es la
   misma clase de trampa que el offset horario de Channex: un parámetro que parece la solución,
   no lo es, y no protesta.

4. **Lo que sí funciona es enumerar `status`**, y solo en forma de **parámetros repetidos**
   (`status=new&status=confirmed&…`). La forma con comas devuelve `400`. El vocabulario está
   validado en servidor —`status=bogus` responde `400` nombrando el parámetro— y tiene seis
   valores: `new`, `request`, `confirmed`, `cancelled`, `inquiry` y `black`.

**Consecuencia para el adapter**, ya implementada: toda listado envía los cinco estados que son
reservas. Excluir `black` de esa enumeración sale gratis y es de paso la exclusión de bloqueos de
calendario en la consulta que el diseño prefería.

**Coste de la enumeración**: es una allowlist, así que un estado que Beds24 añada en el futuro
sería invisible hasta que alguien lo añada. Se acepta porque la alternativa es perder las
cancelaciones hoy.

### Una cancelación por API no rellena `cancelTime`

**Medido el 2026-08-06.** Cancelar con `POST /bookings` + `status: cancelled` mueve `status` y
`modifiedTime`, y deja **`cancelTime: null`**. El fixture `bookings_cancelled.json` lo recoge.

No afecta al mapeo, que lee `status` y no `cancelTime`. Se documenta porque el campo existe, se
llama exactamente como uno esperaría, y está vacío justo en el camino que usamos.

### Hallazgos del formato de petición

- **`arrivalFrom` / `arrivalTo` exigen `YYYY-MM-DD`.** Una duración ISO-8601 (`P0D`, `P90D`) da
  `400` con el mensaje *"Parameter arrivalFrom is in an invalid format. Expected format:
  YYYY-MM-DD"*. El catálogo las enviaba así al principio, así que **dos de las cuatro formas de
  `/bookings` no medían nada**: devolvían 400 y el sondeo lo habría anotado como medición
  fallida. Ahora las fechas se calculan como desplazamiento en días desde hoy, que además evita
  que el catálogo caduque.

- **Una petición rechazada NO consume crédito.** Los dos `400` no traen `X-Request-Cost` y el
  remanente no se movió a través de ellos (98 → 97 para las dos juntas, cuando cada llamada
  válida resta exactamente 1). Es útil para `celery-jobs`: un error de validación no gasta
  presupuesto, así que reintentar tras corregir los parámetros es gratis. **No extrapolar a los
  `429`**, que son otra cosa.

- **Filtrar por un id cuesta lo mismo que pedirlo todo** (`/properties` y `/properties?id=`, 1
  crédito ambas). Con una sola propiedad no dice mucho, pero apunta a que el coste no se abarata
  por acotar.

### Cadencia máxima sostenible del sync

**Medida el 2026-08-04.** Registro crudo en
[`beds24-request-cost.jsonl`](beds24-request-cost.jsonl); tabla generada con
`beds24_probe.py report`.

- Ciclo de sync completo (las 10 formas del catálogo): **10 créditos**
- Ventana del proveedor: **100 créditos / 300 s**, por cuenta
- Ciclos por ventana: **10**
- **Cadencia máxima sostenible: un sync cada 30 s por cuenta**

> **Corregido el 2026-08-06 (de 8 créditos / 24 s a 10 / 30 s), y no es una re-medición: es un
> catálogo que ahora incluye la consulta que el sync hace de verdad.** El catálogo original
> medía `/bookings` por ventana de llegada; el adapter real filtra por **fecha de modificación**,
> dos formas que antes no existían. Las diez cuestan 1 crédito cada una, así que el coste por
> petición no ha cambiado — lo que ha cambiado es cuántas peticiones son «un ciclo».
>
> **Nada de lo que dependía del número anterior se cae**, y conviene decirlo porque la cifra se
> cita en tres sitios. El argumento de la regla 9 de `steering/security.md` —que sincronizar al
> techo produciría del orden de miles de filas de `AuditLog` al día por credencial, saturando el
> índice por actor— sale igual con 30 s (~2.880/día) que con 24 s (~3.600/día).

> ⚠️ **Ese número es un techo, no una recomendación, y confundirlo sería el error caro.**
>
> Esa cifra es lo que el **presupuesto de créditos** permite. Beds24 **desaconseja explícitamente
> el uso en tiempo real y recomienda sincronización completa cada ~6 h** (ADR 0006). Las dos
> cosas no se contradicen: el límite de créditos protege su infraestructura de picos, la
> recomendación habla de carga sostenida y uso razonable. Sincronizar al techo porque «cabe» es
> la clase de lectura que acaba en una conversación con su soporte.
>
> Lo que esta medición aporta a `celery-jobs` no es «poll al techo», es **holgura**: la cadencia
> que el producto necesite —minutos, no horas, para que el dashboard responda en <10 s— cabe
> sobradamente dentro del presupuesto, y no hace falta diseñar contra la restricción. Eso era
> justo la incógnita que ADR 0006 dejó abierta.
>
> Y sigue vigente el aviso de la sección anterior: **medido sobre una cuenta vacía**. Con
> reservas dentro el coste por ciclo puede subir, y con él baja la holgura.

### ⛔ Latencia de los webhooks — NO MEDIBLE en una cuenta sin canales

**No medido, y no por falta de tiempo: por una contradicción entre dos requisitos.**

Medido el 2026-08-04: se configuró el webhook por API contra un túnel efímero (camino verificado
de punta a punta con un `POST` manual que el receptor registró en 246 ms), se creó una reserva
por API, y **no llegó ningún webhook**. El túnel seguía vivo — comprobado con una segunda
petición manual después de esperar.

La causa está en la documentación del proveedor: *«When a booking is created, modified or
cancelled **by a channel**, Beds24 will send a notification push to a URL specified by you»*.
**Los webhooks se disparan para reservas de canal.** Una reserva creada por API tiene
`channel: "direct"` y `referer: "API"` —lo confirma el fixture capturado— y no dispara nada.

Y ahí está el choque: **R6.1 prohíbe conectar ningún canal OTA a esta cuenta**, porque REDES11 y
PAJARITOS8 están vendiendo y Airbnb admite un único channel manager por cuenta. Medir la
latencia de los webhooks exigiría exactamente lo que la regla dura prohíbe.

**Verificado que no falta activar nada.** La página Settings → Properties → Access muestra la
sección *Booking Webhook* con exactamente los cuatro campos que la API escribe —Webhook Version,
URL, Custom Header, Additional Data— y **ningún interruptor adicional ni lista de eventos**. El
objeto que se configura por API es la configuración completa. Se comprobó porque la
documentación menciona esa ruta y describe los booking webhooks como función *beta*, lo que hacía
razonable sospechar de un paso de habilitación aparte; no lo hay.

No es un fallo del banco: el receptor, el túnel, la configuración por API y la correlación por
`booking_ref` funcionan y están probados. Lo que falta es un evento que el proveedor considere
digno de webhook.

`Additional Data` quedó descartada como causa al abrir su desplegable: no controla el disparo
sino el contenido, y lo que controla merece sección propia (abajo).

**Qué queda sin responder**, y hereda `reservations-webhooks`: la latencia real, el
comportamiento ante desorden (R2.4) y si la cabecera estática llega como se configuró (R2.5).

**Vías para cerrarlo más adelante**, ninguna gratis:

1. **Medir durante la ventana de corte de `pms-beds24-adapter`**, cuando los canales se conecten
   de verdad a Beds24. Es el momento natural y no cuesta una cuenta extra, pero llega tarde para
   diseñar `celery-jobs`.
2. **Una segunda cuenta de Beds24 con un canal de test**. Ningún proveedor evaluado salvo Channex
   da sandbox de OTA (ADR 0006), así que «canal de test» aquí significa un anuncio real en una
   OTA real. Coste y riesgo propios.
3. **Preguntar a soporte** si existe un modo de disparo para reservas de API. La documentación
   menciona que los booking webhooks son *beta* y piden contactar; puede que haya un ajuste en
   Settings → Properties → Access → Booking webhooks que la API no expone.

**Lo que sí queda demostrado y vale para `reservations-webhooks`**: la configuración del webhook
**se hace por API** (contradice ADR 0006, ver arriba), el `customHeader` viaja en la
configuración, y el receptor con anonimización previa a disco funciona.

### Orden de llegada de los webhooks

**No medido.** ADR 0006 afirma que el proveedor no garantiza el orden. `reservations-webhooks`
depende de ello, así que se comprueba en vez de asumirse.

### Forma real de los payloads de reserva

**Medida el 2026-08-04.** Fixture anonimizado en
`backend/tests/integrations/fixtures/beds24/bookings.json`, capturado de una reserva real creada
por API.

Una reserva de Beds24 trae **73 campos**. Los que el mapeo a `ReservationDTO` necesitará:
`id`, `status`, `roomId`, `propertyId`, `arrival`, `departure`, `numAdult`, `numChild`, `price`,
`commission`, `channel`, `referer`, `bookingTime`, `modifiedTime`, `cancelTime`.

Tres cosas que conviene saber antes de escribir ese mapeo:

- **Hay diez campos `custom1`…`custom10`** de texto libre. Son el sitio donde un operador mete lo
  que sea, así que la política fail-closed los scrubbea por defecto y eso es correcto.
- **Hay dos campos con forma de credencial de pago**: `stripeToken` y `pcibookingToken`. En esta
  captura llegaron `null` —cuenta sin canales, sin pagos— pero existen en el esquema, y la
  aguja `token` del anonimizador ya los cubre. La regla 13 aplica aquí aunque hoy vengan vacíos.
- **`channel` y `referer` distinguen el origen**: esta reserva trae `"direct"` y `"API"`, que es
  justo lo que explica por qué no disparó webhook.

**El sobre de escritura**, útil para `pms-beds24-adapter`:

```json
// éxito
[{"success": true, "new": {"id": 90923575, ...}, "info": [{"action":"new booking","id":90923575}]}]
// rechazo de un elemento — OJO: llega con HTTP 201
[{"success": false, "errors": [{"action":"new booking","field":"arrival","message":"invalid"}]}]
// petición malformada — dict, no lista
{"success": false, "code": 400, "error": "Request body must be an array"}
```

**El proveedor responde `201` incluso cuando rechaza la escritura.** El veredicto está en el
cuerpo, no en el estado. Un adapter que se fíe del código HTTP dará por creada una reserva que no
existe.

### Forma real de los payloads de mensaje

**No medido en lectura.** `/bookings/messages` responde 200 pero llega vacío: no hay conversación
sin canal. Mismo bloqueo que la latencia de webhooks.

**Pero eso midió un GET, y la pregunta que decide el aplazamiento es la del POST.** Un GET vacío
prueba que no hay nada que *leer*; no dice nada sobre si el proveedor acepta que le **escribas**
un mensaje sobre una reserva sin canal. Si acepta `source: guest`, el camino de entrada de
`messaging-ai` tiene fuente real hoy y `beds24-messaging-adapter` deja de estar bloqueado entero
— lo que seguiría esperando a la ventana de corte sería leer un hilo de OTA, no ejercitar el
pipeline. Por eso existe el subcomando `messages`:

```bash
export BEDS24_REFRESH_TOKEN=...   # cuenta de medición, nunca la de los pisos
docker compose run --rm --no-deps -e BEDS24_REFRESH_TOKEN backend \
  uv run python scripts/beds24_probe.py messages \
    --room=713992 --confirm-writes --out=/app/beds24-cost.jsonl
```

Lo que conviene saber antes de correrlo:

- **Escribe**, así que exige `--confirm-writes` y pasa por el mismo guard de cuenta que
  `provoke` — aborta si la cuenta no tiene exactamente una propiedad.
- **Crea la reserva enganchándose al `observer` de `provoke`**, no con un ciclo propio. Hay una
  sola vía de creación de reservas en este script a propósito, y `provoke` cancela al final pase
  lo que pase.
- **Prueba `guest` y `host`.** El control decide el significado: `host` aceptado y `guest`
  rechazado significa que el límite es de *dirección*; ambos rechazados, que es del canal
  ausente. Solo el primero de esos dos escenarios desbloquea trabajo.
- **El cuerpo de `POST /bookings/messages` no está documentado** en nada que hayamos medido —
  ADR 0006 registra el endpoint y su vocabulario de `source` y nada más. El sondeo prueba dos
  formas y para en la primera que no rechacen; una petición rechazada no consume crédito y
  `_envelope_failure` devuelve el mensaje **por campo** del proveedor, que es lo que convierte
  un rechazo en la respuesta de cuál era la forma correcta.
- **Ojo al `201` que rechaza.** El veredicto va en el cuerpo, no en el estado; leer solo el
  status reportaría «la mensajería funciona sin canal», que es justo la respuesta equivocada en
  la única pregunta que esto existe para responder. Hay test dedicado.

**Resultado: pendiente de ejecutar.** Cuando se corra, el veredicto se escribe aquí y, si sale
que `guest` se acepta, hay que revisar el `deferred-until:` de `beds24-messaging-adapter` en el
roadmap, que hoy afirma que sin canal «no hay conversación que leer ni reserva de OTA a la que
responder».

### Límite de tasa

**No medido, y no se va a medir provocándolo.** El modelo publicado —100 créditos / 5 min por
cuenta— se toma como dado y el consumo de un ciclo se deriva sumando costes medidos.

---

## Firma de webhooks: la respuesta es que no la hay

`reservations-webhooks` arrastra en su enunciado *«validando firma HMAC cuando el provider la
soporte»*. **Beds24 no la soporta**, y esto no está pendiente de medición: ADR 0006 establece
que **ninguno** de los once proveedores evaluados firma sus webhooks. Beds24 ofrece únicamente
una **cabecera estática que configuras tú**, sin API de suscripción y sin garantías de orden.

Eso convierte el requisito en otra cosa. No es «valida la firma»: es **«trata todo webhook como
un aviso no fiable y re-lee el estado por API»**, que es una arquitectura distinta y más cara.
La regla 12 de `steering/security.md` ya la recoge entera, y en particular su punto (d) —la
re-lectura desacoplada del volumen de peticiones, encolada y coalescida— existe precisamente
porque un endpoint sin firma que dispara una llamada saliente por webhook recibido convierte un
problema de integridad en uno de disponibilidad: quien adivine la ruta agota la cuota de la
cuenta y detiene el sync legítimo.

Con el modelo de créditos de Beds24 eso no es teórico. La cuota es **por cuenta**, 100 cada 5
minutos, así que el coste de agotarla es exactamente el coste de parar la sincronización de
todas las propiedades a la vez.

---

## ⚠️ Beds24 puede enviarte el CVC en un webhook

Descubierto el 2026-08-04 al abrir el desplegable **Additional Data** de Settings → Properties →
Access. Sus cuatro valores:

```
None  ·  CVC  ·  Token  ·  CVC and Token
```

No decide *cuándo* se envía el webhook. Decide si el cuerpo lleva el **código de seguridad de la
tarjeta** y el token de pago.

Esto engancha directo con la **regla 13** de `steering/security.md`, que es categórica porque
**PCI DSS prohíbe retener el CVV** — cifrarlo no basta, no puede persistirse en absoluto. Y
`reservations-webhooks` está diseñado para persistir el cuerpo crudo en `webhook_events` con
`processed=FALSE` y procesarlo después, así que un ajuste puesto en `CVC` metería datos de
tarjeta en una columna que la regla 11 exige limpia, **sin que nadie escriba una línea de código
que parezca una violación**.

Es el mismo patrón que ADR 0006 ya anticipó para los códigos de acceso: *«el PIN vuelve a
nosotros en los payloads … y aterrizaría en claro en `webhook_events.payload` … saltándose las
reglas 3 y 4 sin que nadie escriba una línea que parezca una violación»*. Aquí no es un PIN, es
un CVC, y no hace falta elegir ninguna arquitectura de accesos para exponerse: basta con que
alguien toque un desplegable.

**Lo que este change hace al respecto**: `beds24_probe.py` escribe `additionalData: "none"` como
**constante**, no como parámetro — no hay argumento que un llamante pueda pasar para ampliarlo, y
hay un test que lo fija.

**Lo que heredan `reservations-webhooks` y `pms-beds24-adapter`**:

1. El ajuste se queda en `None`, y conviene **verificarlo por API** al arrancar en vez de confiar
   en que nadie lo tocó — es legible en `GET /properties`, así que es una aserción barata.
2. Si algún día se pusiera en `CVC`, el descarte tiene que ocurrir **en recepción, antes de
   escribir `webhook_events`**. Como ya avisa ADR 0006, la arquitectura que persiste primero y
   procesa después llega tarde: el dato ya estaría en la columna.

## Consecuencia para la infraestructura: el webhook necesita un camino desde internet

Surgido al preparar la medición (2026-08-04), y no es un detalle del spike: es una entrada de
diseño para `reservations-webhooks` y un **segundo disparador** para una entrada aplazada.

En producción, Beds24 tiene que hacer `POST` contra
`/api/v1/webhooks/{provider}/{webhook_token}` **desde internet**. Hoy eso no es posible en el
entorno dev de Oracle:

- El túnel de Cloudflare enruta **solo** a `frontend:3000`. El backend escucha en el loopback de
  la VM y solo se alcanza por túnel SSH.
- `ingress-https-hardening` **R1.2** va justo en la dirección contraria a propósito: deja a
  `cloudflared` **sin poder resolver `backend`**, para que quien controle el API token de
  Cloudflare no pueda publicar `backend:8000` ni `postgres` reescribiendo una regla de ingress.

### Por qué el análisis heredado de `api-ingress-routing` no cubre este caso

Esa entrada está aplazada con una condición de disparo observable: *«se reabre cuando
`getDashboardDataSource()` deje de devolver un mock»*. Todo su análisis razona sobre **el
navegador** llegando a `/api`, y concluye —bien— que no hace falta exponer el backend, sino un
camino **same-origin** bajo el hostname público del frontend, vía `rewrite` de Next.js.

Un webhook no encaja en ese razonamiento. **No es el navegador y no es same-origin**: es un
tercero entrando desde fuera. Las consecuencias que el análisis heredado no contempla:

1. **El disparador se queda corto.** `reservations-webhooks` necesita el camino aunque
   `getDashboardDataSource()` siga devolviendo un mock, así que hay un segundo disparador,
   independiente del primero y que puede llegar antes.
2. **La vía same-origin cambia de coste.** Enrutar las llamadas de Beds24 por el servidor de
   Next mete un salto que no existía y convierte a Next en parte de la superficie que la
   **regla 12** obliga a proteger: límite de tasa, tope de cuerpo, y la ruta no adivinable. Con
   el navegador esas obligaciones vivían en el backend; con un webhook empiezan antes.
3. **La vía «segunda regla de ingress al backend» sigue cerrada**, y ahora por partida doble: ya
   chocaba con R1.2 de `ingress-https-hardening`, y un endpoint de escritura anónimo es
   precisamente lo que no conviene colgar de una regla que el API token de Cloudflare puede
   reescribir.

### Qué NO decide este spike

La solución. Aquí solo consta que el camino hace falta, por qué las dos vías conocidas no valen
tal cual, y que la condición de disparo de `api-ingress-routing` debería recoger este segundo
caso. Elegir la topología es alcance de esa entrada o de `reservations-webhooks`, con su propio
análisis.

Nota operativa: nada de esto afecta a **medir**. La medición usa un túnel efímero contra
`localhost`, sin tocar la VM de Oracle ni su ingress.

## Contradicciones con ADR 0006

Se rellenan al medir. Si una medición contradice lo que el ADR afirma, **se señala aquí y el
ADR no se enmienda en este change** — enmendarlo es una decisión con su propio alcance.

### 1. ⚠️ Los webhooks SÍ tienen API — ADR 0006 se equivoca

ADR 0006 afirma que Beds24 **no tiene API de suscripción** de webhooks y que «se configuran por
propiedad desde la UI, sin API de suscripción». **Es falso.** Medido el 2026-08-04 con un viaje
completo de ida y vuelta: escribir, releer, limpiar, releer.

`GET /properties` los devuelve:

```json
"webhooks": { "version": "one", "url": "", "additionalData": "none", "customHeader": "" }
```

Y `POST /properties` los **escribe**, con coste de 1 crédito:

```json
// POST /properties  [{"id":345754,"webhooks":{"version":"one","url":"https://…","additionalData":"none","customHeader":"X-Probe: 1"}}]
// 201 Created
[{"success": true, "modified": {"webhooks": {"url": "https://…", "customHeader": "X-Probe: 1"}}}]
```

Verificado que persiste releyendo, y devuelto a `""` al terminar.

**Dos consecuencias.** La del runbook es que el paso manual desaparece: el subcomando
`beds24_probe.py webhook --url=… --confirm-writes` configura el destino, así que la URL
cambiante del quick tunnel deja de obligar a volver al panel en cada sesión. La de arquitectura
es mayor: `reservations-webhooks` estaba planificado sobre la premisa de configuración manual
por propiedad, y esa premisa no se sostiene.

**Lo que el ADR sí acertaba** y no cambia: el mecanismo de autenticación es una **cabecera
estática que pones tú** (`customHeader`), no una firma. La conclusión de R5.3 se mantiene
entera — todo webhook se trata como aviso no fiable y se re-lee por API.

De paso, este viaje reveló el **sobre de escritura real** de la API: una lista de un elemento
con `success` booleano y `modified`. Eso es lo que `_extract_booking_ref` tendrá que reconocer
en la respuesta de `POST /bookings`.

### 2. El refresh token NO rota al usarse

Medido el 2026-08-04, y por observación en vez de por experimento: el sondeo canjea el refresh
token en cada ejecución y avisa en mayúsculas si la respuesta trae uno distinto al enviado. Tras
un canje completo **no apareció el aviso**, así que el proveedor devuelve el mismo.

No se probó de forma destructiva a propósito: averiguarlo forzando la rotación habría invalidado
el token guardado por el operador si la respuesta hubiera sido que sí.

Para `pms-beds24-adapter` esto simplifica el diseño: basta con **persistir el refresh token una
vez** y cachear el access token en Redis con TTL. Si rotara habría que reescribir la credencial
cifrada en cada refresh, de forma atómica, y perder esa escritura bloquearía la cuenta a los 30
días. La comprobación se queda en el script de todas formas: es barata y el día que el proveedor
cambie de política, avisa.

### 3. `/properties` no declara los canales conectados

ADR 0006 no lo afirma, pero el diseño de este change lo asumió al escribir el guardia
anti-escritura de R6.1 en términos de «canales conectados». No hay tal campo en la respuesta,
ni con `includeAllRooms=true`. El guardia se rediseñó para contar propiedades, que ataca el
mismo riesgo sin depender de un campo inexistente.

---

## Referencias

- [ADR 0006 — proveedor PMS/Channel Manager](adr/0006-pms-channel-manager-provider.md)
- [`channex-staging.md`](channex-staging.md) — el spike del otro proveedor, y la lista de lo que
  quedaba por medir aquí
- `sdd/changes/pms-beds24-spike/design.md` — decisiones D1-D11
- `sdd/steering/security.md` — reglas 3, 8, 12 y 13
