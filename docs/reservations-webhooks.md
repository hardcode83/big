# Webhooks de reservas

Cómo se **opera** la vía por la que el PMS nos avisa de que una reserva cambió: dar de alta el
endpoint de un tenant, pegar sus dos secretos en el proveedor, rotarlos, y qué hacer cuando algo no
llega. El *qué hace* el sistema vive en `sdd/specs/reservations-webhooks.md` (lo escribe la fase de
archivado); aquí va el *cómo se trabaja con ello*.

Lo primero, porque cambia cómo se lee todo lo demás: **el aviso nunca es la fuente de verdad**.
Ninguno de los once proveedores evaluados firma sus webhooks ([ADR 0006](adr/0006-pms-channel-manager-provider.md)),
así que el cuerpo que llega es texto que cualquiera podría haber enviado. Lo que hacemos con un aviso
es **releer por API** al proveedor y quedarnos con lo que responda. El cuerpo solo dice *dónde mirar*.

## Las dos mitades del secreto

Cada tenant tiene, por proveedor, **un endpoint** con dos secretos que acuñamos nosotros:

| Mitad | Qué es | Dónde vive en nuestro lado |
|---|---|---|
| **Token de ruta** | Un valor opaco dentro de la URL: `POST /api/v1/webhooks/{provider}/{token}` | Guardado **hasheado**; es además lo que resuelve el `tenant_id` |
| **Secreto de cabecera** | El valor de una cabecera estática que configuras en el proveedor | Guardado **cifrado** (Fernet), comparado en tiempo constante |

Son dos y no una a propósito: se sostienen mutuamente. Un volcado de cabeceras pierde la segunda pero
no la primera; un log de peticiones registra la primera pero no la segunda.

**El coste declarado de llevar el token en la ruta**: un path es lo único que todo servidor, proxy y
agregador guarda por defecto. Dentro del proceso está cerrado (`app/core/log_redaction.py` lo redacta
en el log de acceso, y el limitador de tasa usa el hash y no el valor), pero **fuera no**: el túnel de
Cloudflare de [ADR 0003](adr/0003-https-ingress-dev.md) registra el URI completo en los logs del borde.
Hoy se acepta porque el entorno es de una sola persona y esos logs son suyos. **La Transform Rule que
redacte `/api/v1/webhooks/*` en el borde es requisito antes de que entre el primer tenant real**, no
una mejora opcional: con un segundo cliente, «visible para quien administra el túnel» deja de
significar «visible para su dueño».

## Dar de alta un endpoint

Lo hace el **`TENANT_OWNER`** (permiso `MANAGE_TENANT_SETTINGS`), no quien gestiona reservas: acuñar
este material decide *quién puede escribir en el tenant desde internet*, para todas las viviendas a la
vez. Eso es un acto de configuración.

```bash
curl -X POST https://<host>/api/v1/integrations/webhook-endpoints \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"provider": "BEDS24", "header_name": "X-AutoHost-Webhook"}'
```

`header_name` es **el nombre de la cabecera, no su valor** — el valor lo minta el sistema. El nombre lo
eliges tú porque acaba en el panel del proveedor; cualquier cosa que empiece por alfanumérico y siga
con alfanuméricos o guiones vale.

La respuesta (`201`) es **la única vez que los dos secretos se serializan**:

```json
{
  "id": "…",
  "provider": "BEDS24",
  "header_name": "X-AutoHost-Webhook",
  "webhook_url": "https://<host>/api/v1/webhooks/beds24/<token>",
  "header_secret": "…",
  "notice": "Copy the URL and the header secret into the provider's panel now: …"
}
```

**No hay endpoint de lectura**, ni siquiera enmascarado: la regla 3(a) de `sdd/steering/security.md`
permite entregarlos «una sola vez al generarlos y en cada rotación», y una lectura enmascarada sería
una segunda serialización que la excepción no cubre. Si se pierden, se rotan. No hay otra vía, y es
deliberado.

Un segundo alta para el mismo proveedor responde **`409`**: reemplazar material vivo es lo que hace
`rotate`, no un alta que dejaría el anterior huérfano sin decírselo a nadie.

## Pegarlos en el proveedor

### Beds24

Dos caminos, y el segundo es el que descubrió el spike:

- **Panel**: Settings → Properties → Access → *Booking Webhook*. Cuatro campos —Webhook Version, URL,
  Custom Header, Additional Data— y ningún interruptor extra ni lista de eventos que activar; se
  comprobó expresamente porque la documentación describe los booking webhooks como *beta*.
- **API**: `POST /properties` con el objeto `webhooks`, coste 1 crédito. Es lo que usa el subcomando
  `beds24_probe.py webhook --url=… --confirm-writes`.

En los dos casos, ojo con la forma del campo: **`customHeader` es una sola cadena `Nombre: valor`**,
no dos campos. Con lo de arriba sería `X-AutoHost-Webhook: <header_secret>`.

Y **la configuración es por propiedad**, no por cuenta: cada vivienda del tenant apunta a la misma URL.
La granularidad de nuestro material es por tenant (regla 12(a)), así que el token es el mismo para
todas — es el proveedor el que obliga a repetir el pegado.

Detalle medido en [`beds24-spike.md`](beds24-spike.md) §«Los webhooks SÍ tienen API — ADR 0006 se
equivoca» y §«Latencia de los webhooks — NO MEDIBLE en una cuenta sin canales».

### Channex

Channex **también** tiene API de configuración de webhooks (contra lo que afirmaba ADR 0006), con
reintentos propios y backoff exponencial hasta 10 intentos por su parte. Ver
[`channex-staging.md`](channex-staging.md) §Webhooks.

> `EXTERNAL_DEPENDENCY` — **nunca se ha visto llegar un webhook real de ningún proveedor a este
> receptor.** La cuenta de desarrollo de Beds24 no puede tener canales OTA conectados (regla dura del
> spike: REDES11 y PAJARITOS8 están vendiendo, y Airbnb admite un único channel manager por cuenta), y
> una reserva creada por API no dispara aviso. Así que **queda sin verificar contra un proveedor real**
> que la cabecera estática llegue tal como se configuró, cuál es la latencia de entrega y cómo se
> comporta el orden. Las tres cosas las cierra
> `sdd/roadmap/beds24-webhook-cutover-measurement.md`, durante la ventana de corte. Lo que sí está
> probado es todo lo nuestro: el receptor, el túnel, la configuración por API y la correlación.

## Rotar

```bash
curl -X POST https://<host>/api/v1/integrations/webhook-endpoints/<id>/rotate \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Devuelve la misma respuesta que el alta, con material nuevo. **No hay ventana de gracia**: el par
anterior deja de autenticar en la misma transacción, así que entre la rotación y el momento en que
actualizas el panel del proveedor, **los avisos que lleguen se pierden** — responden `404` como
cualquier otro fallo de autenticación.

**Y eso no pierde reservas.** Lo que se pierde es el *aviso*, no el cambio: el sondeo
`python -m app.integrations.cli.pms_sync <tenant>` relee el mismo material por API y recoge lo que haya
cambiado. El webhook es el camino rápido; el sondeo es el suelo. Por eso la rotación es una operación
barata y no una ventana de mantenimiento — y por eso conviene hacerla, no evitarla, si hay cualquier
duda sobre dónde acabó un secreto.

Alta y rotación dejan rastro en el log de auditoría (`WEBHOOK_ENDPOINT_CREATED`,
`WEBHOOK_ENDPOINT_ROTATED`, entidad `WEBHOOK_ENDPOINT`), con actor e IP. La **lectura** no se audita, y
es una exención razonada de la regla 3(b): no existe lectura que auditar mientras no exista endpoint que
la haga.

## Qué pasa cuando llega un aviso

1. El receptor responde **`202` sin cuerpo** y encola la fila en `webhook_events` con
   `processed = FALSE`. No relee nada aquí: eso es trabajo del job.
2. `process_webhook_events` corre **cada 60 s**, toma el lote pendiente, lo agrupa por tenant y por
   proveedor, y emite **una** llamada de re-lectura por destino — todos los avisos de un tick para un
   proveedor caben en una sola llamada.
3. Lo que la re-lectura devuelva entra por el mismo ingest que el sondeo, y las transiciones de estado
   las hace `AdvancePropertyStatesUseCase`, sin tocar.

La cadencia de 60 s **es un parámetro de seguridad, no de tuning**: como el job coalesce todo un tick en
una llamada por destino, la cadencia *es* el techo de llamadas salientes al proveedor. Acortarla lo sube.
Está escrito así en `backend/app/scheduler/schedule.py`.

La ventana de re-lectura empieza **una hora antes** del aviso más viejo del grupo
(`RE_READ_LOOKBACK`, marcado `ASSUMPTION` en el código). No puede ser cero: un aviso anuncia algo que
*ya ocurrió*, así que anclar en el propio aviso pediría al proveedor lo cambiado desde un instante
posterior al cambio — excluyendo justo la reserva que el aviso señalaba. La hora es generosa porque la
latencia real del proveedor está sin medir, y no cuesta llamadas: el número de llamadas lo fija el
agrupado, no la anchura de la ventana.

### Fallos y reintentos

Un aviso que falla se reintenta **hasta 3 veces**, con espera de 1, 2 y 4 minutos (`attempts` y
`next_attempt_at` viven en la propia fila — [ADR 0007](adr/0007-webhook-event-retry-columns.md) — para
que un reinicio del worker no reprocese ni pierda la cuenta). Agotado el presupuesto deja de
seleccionarse, pero **la fila se queda**, con su código, para diagnóstico:

| Código | Qué significa | Qué hacer |
|---|---|---|
| `PROVIDER_UNAVAILABLE` | No se pudo releer al proveedor dentro del presupuesto — o el `provider` de la fila no lo sirve ningún adapter | Mirar credenciales y disponibilidad del PMS; `pms_sync` recupera lo perdido |
| `UNMAPPABLE` | La re-lectura respondió, pero el ingest no pudo convertirlo en reserva | Suele ser inventario: la propiedad no existe o su `pms_external_id` está duplicado |
| `UNATTRIBUTED` | La fila no tiene tenant | No debería ocurrir: el token es lo que resuelve el tenant. Gasta el presupuesto de golpe (reintentar no inventa un tenant) y emite un `warning` |

Un aviso que falla **falla solo**: no arrastra a los demás del lote, ni a los de otro proveedor del
mismo tenant.

### Leerlo en el informe del job

```bash
docker compose logs -f worker | grep process_webhook_events
```

Cada ejecución informa `selected`, `processed`, `failed`, `unattributed`, `tenants` y `skipped_locked`.
`skipped_locked` significa que la ejecución anterior seguía viva y esta no hizo nada — es el mismo
nombre que usan los demás jobs para el mismo suceso, a propósito. Ver
[`celery-jobs.md`](celery-jobs.md) para cómo se arranca y se mira el scheduler.

## Límites de tasa

Dos, y defienden de cosas opuestas (`.env.example` lleva los dos comentados con su valor por defecto;
no son secretos, así que llevan default):

- **`WEBHOOK_RATE_LIMIT_PER_MINUTE`** (120) — por **token**, es decir por tenant. Generoso: protege la
  tabla del tráfico legítimo desbocado de un proveedor, y su radio de daño es un solo tenant. Solo se
  cobra a quien ya ha demostrado tener los dos secretos, para que nadie con solo la URL pueda gastar el
  presupuesto de un tenant y tumbarle la integración.
- **`WEBHOOK_PROBE_LIMIT_PER_MINUTE`** (20) — por **IP**, y cuenta **solo las peticiones que fallan la
  autenticación**. Es lo que hace que adivinar una ruta cueste algo. Cuenta fallos y no peticiones
  porque un proveedor envía desde pocas IPs en nombre de muchos tenants: un límite por IP sobre el
  tráfico bueno los estrangularía a todos a la vez.

No hay `WEBHOOK_MAX_BODY_BYTES`: el tope de cuerpo ya lo pone `REQUEST_MAX_BYTES`, aplicado a todo
`/api/v1/` antes del enrutado.

**Todavía no hay allowlist de IPs del proveedor.** Se revisará al llegar a 25-50 unidades o a la primera
rotación que provoque un `429` cruzado, lo que ocurra primero.

## Diagnóstico: por qué el proveedor recibe un `404`

El receptor responde **exactamente el mismo `404`, con el mismo cuerpo**, para un proveedor
desconocido, un token desconocido, una cabecera ausente y una cabecera con valor incorrecto. Es
deliberado —un `401` distinguible sería un oráculo para adivinar tokens— y tiene el precio de que
**por la respuesta no se puede saber cuál de las cuatro cosas falla**. Descártalas en orden:

1. **El segmento del proveedor**, en minúsculas y tal como lo devolvió el alta (`beds24`, `channex`).
2. **La URL completa**, sin recortar: el token es el último segmento y no lleva sufijo.
3. **El nombre de la cabecera**, exactamente el que pasaste en `header_name`.
4. **El valor de la cabecera**. Si dudas, **rota** — es más rápido que demostrar que el valor
   almacenado es el que crees, y no puedes leerlo de vuelta por diseño.

Otras respuestas del receptor: **`429`** (alguno de los dos límites de arriba) y **`413`** (cuerpo por
encima del tope de `/api/v1/`; no se escribe ninguna fila).

Un cuerpo que no es JSON válido de un llamante **autenticado** no es un error: se encola con payload
vacío, porque el cuerpo no decide nada y una fila visible se diagnostica mejor que un aviso descartado.

## Datos de tarjeta en el texto libre

Dos redactores, en la misma frontera:

- **`scrub_card_data`** limpia el payload entrante antes de que se escriba nada.
- **`free_text.py`** redacta **rachas de 13 dígitos o más** (ignorando espacios y guiones Unicode) en
  `special_requests`, y **solo cuando la reserva viene de fuente externa** — webhook o sondeo del PMS.
  Lo que escribe una persona por la API se queda intacto.

> `ASSUMPTION` — el umbral de 13 dígitos supone que **ningún dato operativo real llega a esa
> longitud**: un código de portal español son 4-8 dígitos, un móvil español 9, uno internacional con
> prefijo 11-12. La ventana de falso positivo queda acotada a alguna referencia larga de OTA, que es un
> dato reconstruible desde `external_pms_id`. Si aparece un caso operativo de 13 dígitos o más, la nota
> del huésped llegará al personal de limpieza con esa racha redactada.

Dos bordes aceptados, con test propio cada uno: **el punto no es separador** (`4111.1111.1111.1111`
sobrevive, porque los puntos unen decimales, fechas, versiones e IPs), y **el salto de línea sí lo es**,
así que dos números cortos en líneas consecutivas pueden sumar 13 dígitos y redactarse juntos.

Y uno que **no** se redacta: `csv_parser.py` llena `special_requests` sin pasar por aquí, porque el
import de CSV es un fichero que sube un operador autenticado, no una escritura anónima desde internet.
Se revisará si el CSV deja de ser una reintroducción revisada por una persona y pasa a ser reingesta
cruda de una exportación del PMS.
