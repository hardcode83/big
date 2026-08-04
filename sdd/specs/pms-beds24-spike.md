# PMS Beds24 (banco de medición)

## Purpose

Herramientas de medición contra la API V2 de Beds24, el proveedor PMS que
[ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) elige para el MVP, y los
hallazgos que produjeron. **No hay código de producto aquí**: no existe `Beds24Adapter` ni
`PMSAdapterFactory` ni ninguna `beds24_*` en `app/core/config.py`. La salida es la entrada de
diseño de `celery-jobs`, `reservations-webhooks` y `pms-beds24-adapter`.

Existe porque el coste por petición de Beds24 es **dinámico y no publicado**, y la cadencia del
scheduler es una función de ese presupuesto: no se puede derivar de la documentación, hay que
medirlo. Operación y hallazgos completos: [`docs/beds24-spike.md`](../../docs/beds24-spike.md).

## Requirements

### Transporte y credencial

- THE SYSTEM SHALL leer `BEDS24_REFRESH_TOKEN` **solo del entorno** y canjearlo por el access
  token de 24 h, manteniéndolo **únicamente en memoria** — nunca en disco, ni siquiera como
  caché de sesión.
- THE SYSTEM SHALL rechazar una credencial vacía o ausente **antes de emitir petición alguna**,
  nombrando la variable.
- THE SYSTEM SHALL no incluir el valor del refresh token ni del access token en ningún `repr`,
  log, mensaje de error o traceback, **incluida su forma escapada** (`repr`), porque un token
  con un salto de línea llega embebido así en el error de la capa HTTP.
- WHEN el canje devuelve un refresh token distinto al enviado, THE SYSTEM SHALL avisarlo de
  forma destacada por stderr **sin imprimir el valor**: una rotación obliga a persistir la nueva
  credencial de forma atómica, y perder esa escritura bloquea la cuenta a los 30 días.
- THE SYSTEM SHALL rechazar cualquier argumento no reconocido **sin imprimir su valor**, que
  podría ser la credencial. La cabecera estática del webhook se lee de `BEDS24_WEBHOOK_SECRET`
  y **no** se acepta como argumento, por la misma razón.

### Destino de las peticiones

- THE SYSTEM SHALL comparar el **hostname exacto** de cada URL contra una allowlist constante
  (`beds24.com`), nunca una subcadena de la URL: `api.beds24.com.evil.tld` contiene el host real.
- THE SYSTEM SHALL exigir esquema **`https`**. El refresh token es credencial **de cuenta** —da
  escritura sobre todas sus propiedades— y en claro basta un `s` omitido para publicarla.
- THE SYSTEM SHALL derivar la allowlist de una constante y **no** de `BEDS24_BASE_URL`: quien
  controle el entorno controlaría el destino, que es el ataque del que protege.

### Medición de coste

- THE SYSTEM SHALL registrar por cada petición el `X-Request-Cost` devuelto junto al endpoint, el
  método, la **forma** de la petición, las cabeceras de crédito restante, el estado y el instante
  UTC, en un JSONL de una línea por petición.
- THE SYSTEM SHALL tratar el coste como **decimal**: el proveedor factura fraccionariamente
  (`1,1` en las escrituras) y un parseo entero registraría esos valores como no medidos,
  produciendo un presupuesto optimista.
- WHEN el proveedor no devuelve `X-Request-Cost`, THE SYSTEM SHALL registrar `null` y **nunca
  `0`**: un coste desconocido y uno nulo llevan a presupuestos distintos.
- THE SYSTEM SHALL medir cada endpoint con **al menos dos formas** de petición, porque una sola
  no distingue un coste fijo de uno proporcional.
- THE SYSTEM SHALL enviar las fechas como `YYYY-MM-DD` calculadas por desplazamiento en días
  desde hoy; una duración ISO-8601 recibe `400` y el catálogo con fechas fijas caducaría.
- THE SYSTEM SHALL derivar la cadencia máxima sostenible del coste medido contra la ventana de
  100 créditos / 300 s, **generando** la tabla desde el registro y no transcribiéndola.
- THE SYSTEM SHALL limitar su propio ritmo con un default conservador y, ante cuota agotada,
  **detenerse** en lugar de reintentar. No SHALL buscar el techo provocándolo: el consumo de un
  ciclo se deriva sumando costes medidos.

### Captura de payloads

- THE SYSTEM SHALL anonimizar **en el momento de capturar**, con la política fail-closed
  compartida en `backend/scripts/anonymise.py`: una hoja sobrevive solo si su clave es dato de
  negocio reconocido, aplicado a hojas de texto, hojas numéricas y **claves de diccionario**,
  juzgando un escalar dentro de una lista como si no tuviera nombre.
- THE SYSTEM SHALL conservar `None` y los booleanos, para que el fixture ejercite la misma
  opcionalidad que el payload real.
- THE SYSTEM SHALL registrar en el fixture qué **rutas de clave anonimizadas** se sustituyeron,
  construidas desde el árbol **limpio**: construirlas desde el original republicaría en la
  cabecera del fichero las claves que el anonimizador borró por ser ellas mismas dato personal.
- THE SYSTEM SHALL desambiguar dos claves distintas que colapsen al mismo placeholder, para que
  anonimizar no borre entradas enteras del fixture.
- THE SYSTEM SHALL registrar el coste de la propia petición de captura: una medición que la
  herramienta no puede emitir es una medición que alguien transcribirá a mano.

### Receptor de webhooks

- THE SYSTEM SHALL sellar cada petición entrante con el instante UTC de **recepción** — ese sello
  es la medición, y un capturador de terceros añadiría su latencia a la magnitud medida.
- THE SYSTEM SHALL pasar el cuerpo por el anonimizador **antes** de escribir a disco, y persistir
  de las cabeceras solo sus **nombres**: una de ellas es la credencial estática del proveedor.
- THE SYSTEM SHALL reducir el destino de la petición a su **profundidad** y, si es corto y
  alfabético, su primer segmento — nunca la ruta literal. La regla 12(b) de
  `steering/security.md` sitúa el token no adivinable **en la ruta**, así que persistirla
  publicaría el secreto.
- THE SYSTEM SHALL correlacionar cada webhook con el sondeo por `booking_ref`, y WHEN la
  identidad no puede establecerse sin ambigüedad THE SYSTEM SHALL devolver `None` en lugar de
  adivinar: un id equivocado produce un número plausible y falso.
- THE SYSTEM SHALL rechazar un `Content-Length` negativo o no numérico, y acotar el cuerpo:
  durante la ventana de medición es un endpoint sin autenticar alcanzable desde internet.
- THE SYSTEM SHALL impedir que cualquier texto derivado de la petición llegue a stderr, y WHEN
  pierde un webhook THE SYSTEM SHALL contarlo y avisar con un mensaje **fijo**.

### Aislamiento de la cuenta

- THE SYSTEM SHALL operar contra una cuenta **sin ningún canal OTA conectado**. Beds24 **no tiene
  entorno de staging**, así que nada cumple el papel que en Channex hace el default apuntando a
  staging, y la protección tiene que ser un chequeo explícito.
- WHERE una subcomanda escribe, THE SYSTEM SHALL exigir `--confirm-writes`, comprobado **antes
  incluso de leer la credencial**.
- THE SYSTEM SHALL verificar antes de escribir que la cuenta tiene **exactamente una propiedad**
  y que el room indicado le pertenece. Se cuenta propiedades en vez de detectar canales porque
  `/properties` **no expone ningún campo de canales**: un chequeo fail-closed sobre un campo
  ausente se negaría siempre, y uno fail-open no protegería nada.
- IF la creación de una reserva falla o devuelve una forma que el sistema no reconoce, THEN THE
  SYSTEM SHALL abortar **antes** de modificar o cancelar, y avisar de que puede haber quedado una
  reserva confirmada sin cancelar: cancelar con un id incierto cancela la reserva de otro.
- THE SYSTEM SHALL fijar `additionalData` a `none` como **constante y no como parámetro** al
  configurar el webhook. Sus valores son `None / CVC / Token / CVC and Token`, es decir, decide
  si el proveedor pone el **código de seguridad de la tarjeta** en el cuerpo — y la regla 13 de
  `steering/security.md` es categórica porque PCI DSS prohíbe retener el CVV.

### Artefactos versionados

- THE SYSTEM SHALL versionar los payloads capturados en
  `backend/tests/integrations/fixtures/beds24/` y alimentar con ellos los tests **sin ninguna
  llamada de red**.
- THE SYSTEM SHALL guardar el registro crudo de coste que respalda el informe, para que los
  hallazgos se deriven de datos revisables y no de una transcripción.
- THE SYSTEM SHALL comprobar que **ningún fixture commiteado**, de cualquier proveedor, contiene
  datos con forma de tarjeta, derivando las agujas del propio anonimizador: un guard más estrecho
  que la función que respalda es cómo se filtró un `expiration_date` en `channex-staging-adapter`.
- THE SYSTEM SHALL mantener estas herramientas fuera de `app/` y excluidas de la imagen.

## Hallazgos con carácter normativo

Medidos el 2026-08-04. Detalle y evidencia en [`docs/beds24-spike.md`](../../docs/beds24-spike.md).

- **Presupuesto de créditos**: un ciclo de sync cuesta **8 créditos**, lo que permite **un sync
  cada 24 s** por cuenta. Es un techo impuesto por la cuota, **no una recomendación**: el
  proveedor desaconseja el tiempo real y sugiere ~6 h. Lo que aporta a `celery-jobs` es holgura.
  Medido sobre una cuenta **vacía**; con reservas dentro el coste por ciclo puede subir.
- **El proveedor responde `201` aunque rechace la escritura.** El veredicto va en el cuerpo, en
  cuatro formas distintas. Un adapter que se fíe del código HTTP dará por creada una reserva que
  no existe.
- **Los webhooks se configuran por API** (`POST /properties`), contra lo que afirma ADR 0006.
- **Los webhooks solo se disparan para reservas de canal.** Una reserva creada por API no dispara
  ninguno, así que **una integración de webhooks de Beds24 no se puede validar sin canales
  conectados**. Lo hereda `pms-beds24-adapter`, que medirá latencia y orden durante su ventana de
  corte.
- **El refresh token no rota** al usarse: basta persistirlo una vez y cachear el access token.
- **Una petición rechazada no consume crédito**; corregir parámetros y reintentar es gratis.

## Key files

- `backend/scripts/anonymise.py` — la política fail-closed compartida; solo la allowlist de
  negocio es por proveedor, y el orden agujas-antes-que-sufijos es contrato.
- `backend/scripts/beds24_probe.py` — transporte, allowlist de host, catálogo de coste, captura,
  guardia de cuenta, escritura de webhook, `provoke` e informe.
- `backend/scripts/beds24_webhook_sink.py` — receptor sellado en UTC, latencia y desorden.
- `backend/tests/integrations/fixtures/beds24/bookings.json` — reserva real anonimizada.
- `docs/beds24-request-cost.jsonl` — registro crudo que respalda el informe.
- `docs/beds24-spike.md` — runbook, rotación de credencial y hallazgos.
