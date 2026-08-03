# Beds24 — runbook de medición y hallazgos

Cómo se opera la cuenta de desarrollo de Beds24 y **qué se midió con ella**. Este documento es
el entregable del change `pms-beds24-spike`: no hay código de producto en él, la salida es la
entrada de diseño de `celery-jobs`, `reservations-webhooks` y `pms-beds24-adapter`.

[ADR 0006](adr/0006-pms-channel-manager-provider.md) elige Beds24 como proveedor del MVP y deja
tres cosas explícitamente sin resolver porque no se pueden resolver leyendo documentación: el
coste real en créditos por petición, la latencia real de los webhooks y la forma real de los
payloads. `channex-staging-adapter` cerró la lista y dejó dicho que **no se extrapola**
(`channex-staging.md` §«Lo que queda por medir en Beds24»). Esto la resuelve.

> **Estado: el banco de medición está construido; las mediciones no se han tomado.**
> Todo lo que aparece abajo como *no medido* lo está porque requiere una cuenta de desarrollo
> de Beds24 que no existe todavía. Ver `sdd/changes/pms-beds24-spike/BLOCKED.md`.

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

### Paso 0 — confirmar los supuestos antes de gastar un solo crédito

El banco se escribió sin cuenta, así que lleva **supuestos marcados como `ASSUMPTION`** en el
código. Confírmalos contra la especificación OpenAPI 3.0 publicada de la API V2 **antes** de la
primera llamada autenticada, porque uno de ellos decide a qué host se manda la credencial:

| Supuesto | Dónde | Qué comprobar |
|---|---|---|
| Host y base de la API | `beds24_probe.py` → `ALLOWED_HOSTS`, `DEFAULT_BASE_URL` | Cuál de `beds24.com` / `api.beds24.com` es el real. **Deja solo ese** en el allowlist. |
| Cabeceras del flujo de token | `beds24_probe.py` → `REFRESH_HEADER`, `ACCESS_HEADER`, `TOKEN_PATH` | Nombres reales del canje refresh → access. |
| Rutas del catálogo | `beds24_probe.py` → `CATALOGUE` | Que `/bookings`, `/properties` y `/inventory/rooms/calendar` existan y sean las que el sync usará. |
| Claves de identidad y de tiempo | `beds24_webhook_sink.py` → `BOOKING_REF_KEYS`, `EVENT_TIME_KEYS` | Qué clave lleva el id de reserva y cuál el instante del hecho. |
| **Escritura de reservas** | `beds24_probe.py` → `BOOKINGS_WRITE_PATH`, los cuerpos de `provoke`, y `_extract_booking_ref` | **El más importante de la tabla**, porque es el único cuyo fallo cuesta una escritura. Confirma la ruta, la forma del cuerpo y —sobre todo— **cómo devuelve el id la respuesta de creación**: si el script no lo reconoce, aborta y te deja una reserva confirmada que hay que borrar a mano. |

Si alguno falla el arreglo es de una línea, pero descubrirlo a mitad de la ventana de medición
cuesta créditos y tiempo del trial.

### Credencial

Beds24 usa su **API V2** (REST, OpenAPI 3.0). El flujo es: código de invitación → refresh token
de larga vida → access token de 24 h. **Esto también es un supuesto** tomado de ADR 0006, no
algo verificado contra la API: forma parte del paso 0.

```bash
export BEDS24_REFRESH_TOKEN=...   # nunca en el repo, nunca en la línea de comandos de otro
```

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
docker compose exec backend uv run python scripts/beds24_probe.py probe \
    --out=/tmp/beds24-request-cost.jsonl
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
docker compose exec backend uv run python scripts/beds24_probe.py report \
    --out=/tmp/beds24-request-cost.jsonl
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

**El receptor y el túnel corren en el mismo lado de la frontera del contenedor.** El sink hace
bind a `127.0.0.1` a propósito: mientras dura la medición es un endpoint **sin autenticar que
escribe a disco**, y su única puerta debe ser el túnel efímero, nunca la LAN. Si lo arrancas
dentro del contenedor con `docker compose exec`, un `cloudflared` del host no lo alcanza — y la
salida obvia a ese problema (bindear `0.0.0.0` o publicar el puerto) es justo lo que abre esa
superficie. Así que ambos van en el contenedor:

1. Levanta el receptor y déjalo corriendo:

   ```bash
   docker compose exec backend uv run python scripts/beds24_webhook_sink.py \
       --out=/tmp/beds24-webhooks.jsonl
   ```

2. En **otra shell del mismo contenedor**, levanta el túnel y copia la URL que imprime:

   ```bash
   docker compose exec backend cloudflared tunnel --url http://127.0.0.1:8099
   ```

   Si `cloudflared` no está en la imagen del backend, la alternativa correcta es correr **las
   dos** cosas en el host (`uv run` desde `backend/`), no publicar el puerto del contenedor.

3. Pega esa URL en el panel de Beds24, por propiedad.
4. Provoca los hechos **con el sondeo**, no a mano:

   ```bash
   docker compose exec backend uv run python scripts/beds24_probe.py provoke \
       --property=<room-id> --confirm-writes --out=/tmp/beds24-request-cost.jsonl
   ```

   > ⚠️ **`provoke` es la única subcomanda que escribe.** Por eso exige `--confirm-writes` y,
   > antes de tocar nada, lee `/properties` y **se niega a continuar si la cuenta tiene algún
   > canal OTA conectado**. Beds24 no tiene entorno de staging, así que ese chequeo es lo que
   > aquí hace el papel que en Channex hacía el default apuntando a staging: lo único que
   > separa una medición de escribir en una vivienda que está vendiendo. Si aborta quejándose
   > de canales conectados, **no insistas**: mira a qué cuenta pertenece tu
   > `BEDS24_REFRESH_TOKEN`.

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
docker compose exec backend uv run python scripts/beds24_probe.py capture bookings messages
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

**No medido.** Requiere la cuenta. La tabla la genera `beds24_probe.py report`.

### Cadencia máxima sostenible del sync

**No medido.** Se deriva de lo anterior. Es la cifra que `celery-jobs` necesita y el motivo de
que este change vaya antes que él.

### Latencia de los webhooks

**No medido.** ADR 0006 afirma ~1 minuto de media, sin fuente propia.

### Orden de llegada de los webhooks

**No medido.** ADR 0006 afirma que el proveedor no garantiza el orden. `reservations-webhooks`
depende de ello, así que se comprueba en vez de asumirse.

### Forma real de los payloads de reserva y de mensaje

**No medido.** Los fixtures vivirán en `backend/tests/integrations/fixtures/beds24/`.

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

## Contradicciones con ADR 0006

Se rellenan al medir. Si una medición contradice lo que el ADR afirma, **se señala aquí y el
ADR no se enmienda en este change** — enmendarlo es una decisión con su propio alcance.

**Ninguna registrada todavía** (nada medido).

---

## Referencias

- [ADR 0006 — proveedor PMS/Channel Manager](adr/0006-pms-channel-manager-provider.md)
- [`channex-staging.md`](channex-staging.md) — el spike del otro proveedor, y la lista de lo que
  quedaba por medir aquí
- `sdd/changes/pms-beds24-spike/design.md` — decisiones D1-D11
- `sdd/steering/security.md` — reglas 3, 8, 12 y 13
