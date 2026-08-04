# Design: pms-beds24-spike

## Context

El repo ya tiene la forma que este change necesita, construida por `channex-staging-adapter`: herramientas de un solo uso contra un proveedor externo en `backend/scripts/` (fuera de `app/`, excluidas de la imagen por `backend/.dockerignore` — decisión D9 de aquel change), fixtures reales anonimizados en `backend/tests/integrations/fixtures/channex/`, y un documento de hallazgos medidos en `docs/channex-staging.md`. El anonimizador **fail-closed** vive hoy dentro de `backend/scripts/channex_probe.py` (`anonymise`, `_anonymise_value`, `_anonymise_key`, `_anonymise_leaf`) y `backend/tests/integrations/test_channex_probe.py` lo prueba, además de parametrizar sobre `sorted(FIXTURE_DIR.glob("*.json"))` para afirmar que **todo fixture commiteado está limpio**.

Lo que no existe: ningún endpoint de webhooks (`backend/app/integrations/api/router.py` lo declara fuera de alcance; `WebhookEventModel` existe pero nada escribe en él), ninguna `PMSAdapterFactory` (solo `build_adapter` en `backend/app/integrations/cli/pms_sync.py`, documentado como paso intermedio), y ningún helper genérico de HTTP con reintentos — cada script construye su propio `httpx.Client`. `httpx>=0.28.1` ya es dependencia de **runtime**.

La suite del backend es **offline por construcción**: cero marcadores personalizados, cero `skipif`, cero tests dependientes de credenciales; el borde HTTP siempre se sustituye con `httpx.MockTransport`. Este change no rompe ese precedente.

## Decisions

### D1 — Todo el banco vive en `backend/scripts/`, y nada entra en `app/`

**Chosen:** dos ejecutables nuevos, `backend/scripts/beds24_probe.py` (sondeo, medición y captura) y `backend/scripts/beds24_webhook_sink.py` (receptor cronometrado). Es la categoría exacta de D9: herramienta desechable contra un servicio externo, no superficie de la aplicación. No se añade ninguna `beds24_*` a `backend/app/core/config.py` porque no hay código de producto que la lea — sería configuración muerta hasta `pms-beds24-adapter`.

Rejected: `app/integrations/cli/beds24_probe.py` junto a `pms_sync.py` — convierte un script de un solo uso en API del paquete desplegado, ya rechazado en D9.

Rejected: reutilizar `ChannexClient` como transporte — está modelado sobre el sobre de respuesta, la paginación y la cabecera `user-api-key` de Channex; nada de eso aplica.

### D2 — El anonimizador se **extrae** a un módulo compartido, con la allowlist como parámetro

**Chosen:** `anonymise` y sus auxiliares se mueven a `backend/scripts/anonymise.py`, con firma `anonymise(payload, *, business_keys: frozenset[str])`. `channex_probe.py` pasa a importarlo con su conjunto actual de claves; `beds24_probe.py` pasa el suyo.

El motivo no es estética: R3.2 exige **la misma** política fail-closed, y duplicar una función de seguridad es exactamente cómo dos copias divergen — la de Beds24 heredaría los tres sitios donde un valor puede esconderse (hoja de texto, hoja numérica, **clave de diccionario**) el día que se escribe y los perdería en la primera corrección que solo se aplique a una. La allowlist sí es propia de cada proveedor: los nombres de campo de Channex no dicen nada de los de Beds24.

Rejected: `from channex_probe import anonymise` — acopla el banco de Beds24 al script de otro proveedor, que además podría borrarse cuando Channex deje de usarse.

Rejected: duplicar las cuatro funciones — la razón de arriba.

**La política no es una allowlist, son seis piezas, y solo una es por proveedor.** `channex_probe.py` construye el fail-closed con `PRESERVED_KEYS` (líneas 62-150), `PRESERVED_SUFFIXES` (161), `PII_PLACEHOLDERS` (189-207), los regex `_IDENTIFIER_KEY` (171) y `_DATE_KEY` (179), y `IDENTIFYING_NUMBER_FLOOR` (187). El módulo extraído parametriza **solo la primera** como `business_keys`; las otras cinco se mueven como constantes compartidas porque son juicios de dominio, no de proveedor: las agujas de PII (`card`/`cvv`/`guarantee`, `mail`, `phone`, `document`, `birth`, `address`, `name`) valen para cualquier payload de PMS, las dos por forma existen precisamente para claves que **ningún** nombre predice, y el suelo de 1.000.000 está dimensionado para el portfolio del proyecto, no para Channex.

Dos consecuencias que hay que escribir antes de tocar nada:

1. **El orden es el contrato.** Las agujas de PII corren **antes** que `PRESERVED_SUFFIXES`, y esa precedencia es lo único que impide que `expiration_date` sobreviva por terminar en `_date` — un dato de tarjeta que ya se filtró una vez a un fixture commiteado, según consta en el comentario de la línea 190. La extracción conserva el orden o reintroduce la fuga.
2. **Cualquier ajuste de las cinco compartidas afecta a los dos proveedores.** Si un payload real de Beds24 obliga a mover una de ellas, no es un cambio local: hay que re-verificar los fixtures de Channex. Es asumible porque `test_channex_probe.py` ya parametriza sobre `sorted(FIXTURE_DIR.glob("*.json"))` y afirma que **todo fixture commiteado está limpio**, así que la regresión sale en la suite y no en una revisión a ojo. Lo que **no** se hace es añadir una segunda copia de una de las cinco «para no tocar Channex»: eso es la divergencia que D2 existe para evitar.

**Restricción sobre la extracción**: `backend/tests/integrations/test_channex_probe.py` debe seguir verde sin cambios de comportamiento, incluida su parametrización sobre todos los fixtures commiteados. Es la red que hace barato este movimiento.

### D3 — Una allowlist incompleta es un resultado aceptable, porque el fallo es hacia el lado seguro

**Chosen:** el conjunto de claves de negocio de Beds24 se escribe con lo que se conozca y se **corrige después de ver el primer fixture**, en un bucle: capturar → leer el fichero → ensanchar la allowlist → recapturar.

Esto es viable precisamente porque la política es fail-closed: una clave que no esté en la lista se sustituye, así que el error por omisión es **sobre-anonimizar** —un fixture menos útil— y nunca filtrar. Escribir la lista contra la documentación del proveedor antes de ver un payload sería repetir el error que `channex-staging-adapter` documenta en su D7 bis.

Rejected: capturar en crudo primero y anonimizar después — R3.2 lo prohíbe, y con razón: el fichero crudo existe en disco durante ese intervalo.

### D4 — La medición de coste es un registro por petición, y se commitea como evidencia

**Chosen:** cada petición del sondeo emite una línea JSON con `endpoint`, `method`, la **forma** de la petición (los parámetros que se sospecha que mueven el coste: tamaño de página, amplitud del rango de fechas, número de propiedades), `x_request_cost`, las cabeceras de crédito restante que vengan, el código de estado y el instante UTC. El fichero se escribe donde diga `--out` y el que se usó para el informe se commitea junto a él, en `docs/beds24-request-cost.jsonl`.

R1.5 —«que el informe se derive de datos y no de una transcripción»— solo tiene efecto si los datos son revisables. El contenido no es sensible: rutas, enteros y marcas de tiempo.

Un `x_request_cost` ausente se registra como `null` y **nunca como `0`** (R1.3): un coste desconocido y un coste nulo llevan a presupuestos distintos.

Rejected: acumular en memoria y escribir solo el agregado — pierde la evidencia por petición, que es justo lo que distingue coste fijo de coste proporcional (R1.2).

### D5 — El informe se **genera** desde el registro, no se transcribe a mano

**Chosen:** `beds24_probe.py` lleva un subcomando `report` que lee el JSONL y renderiza la tabla de coste por endpoint y forma, más la cadencia máxima sostenible derivada (R4.4: coste del ciclo completo contra la ventana de 100 créditos / 5 min). `docs/beds24-spike.md` se escribe en este change con el runbook, la regla dura de R6.1 y la sección de hallazgos marcada **no medido** (R5.2); el operador pega ahí la salida del subcomando.

Rejected: que el script reescriba el `.md` in situ — un generador que edita un documento con prosa escrita a mano es frágil y borra matices en cuanto alguien anota algo entre dos tablas.

### D6 — Los webhooks se reciben en local detrás de un túnel efímero, no en un capturador de terceros

**Chosen:** `beds24_webhook_sink.py` es un servidor HTTP mínimo que sella cada petición entrante con el instante UTC de recepción y vuelca método, ruta, cabeceras y cuerpo a un JSONL. Se expone durante la ventana de medición con un **quick tunnel** de `cloudflared` que el operador levanta y tira; la URL resultante se configura como webhook en el panel de Beds24.

**El cuerpo pasa por el anonimizador de D2 antes de tocar el disco, y las cabeceras también.** El sink es un *receptor de webhooks* en el sentido literal de la regla 13 de `steering/security.md`, que exige descartar los datos de titular de tarjeta *«en el adapter o en el receptor de webhooks, antes de que nada pueda persistirlos, loguearlos o reenviarlos»* — y lo exige **en fase de diseño**. Un sink que escribe el cuerpo crudo es exactamente el patrón prohibido, y sería además incoherente con este mismo documento por partida doble: D3 rechaza «capturar en crudo y anonimizar después» porque *«el fichero crudo existe en disco durante ese intervalo»*, y la tabla de riesgos aplica la regla 13 a la captura de fixtures diciendo que *«la cuenta sin canales OTA hace el caso improbable, pero la regla 13 no depende de eso»*. Lo mismo vale aquí, y por la misma razón: el sink ingiere la misma clase de payload de reserva.

Las cabeceras entran en el anonimizador junto al cuerpo porque una de ellas es la cabecera estática de autenticación (R2.5) — es una credencial, no metadato, y volcarla en claro la publicaría en el JSONL. Se registra su **presencia y su nombre**, nunca su valor.

Frente a lo que hizo `channex-staging-adapter` en su D10 (un capturador externo), aquí importan dos cosas que un servicio de terceros no da: el **sello temporal es nuestro** —es literalmente la magnitud que R2 mide, y no queremos el reloj de un intermediario en medio— y el payload de reserva **no sale de la máquina**, que es lo que exige la regla 13 de `steering/security.md` sobre datos de titular de tarjeta aunque la cuenta no tenga canales OTA conectados.

`cloudflared` no es una dependencia nueva del proyecto: el ingress de dev ya se apoya en él (`specs/ingress-https-dev.md`).

**Nuestra API sigue sin exponer ninguna ruta entrante.** Construirla obligaría a cumplir entera la regla 12 de `steering/security.md` (cabecera con valor por tenant comparada en tiempo constante, ruta con token opaco, límite de tasa, tope de cuerpo, relectura encolada y coalescida), que es el alcance completo de `reservations-webhooks`. El sink tampoco escribe en `webhook_events`.

Rejected: un capturador público tipo webhook.site — reloj ajeno y payloads en un tercero.

Rejected: exponer el sink por el túnel permanente de dev — le da nombre estable y persistencia a una superficie que debe durar lo que dura la medición.

### D7 — Credencial: refresh token de cuenta en el entorno, access token solo en memoria

**Chosen:** el script lee `BEDS24_REFRESH_TOKEN` del entorno, lo canjea al arrancar por el access token de 24 h que documenta ADR 0006 para la API V2, y **no escribe ninguno de los dos en disco** — ni en el JSONL, ni en los fixtures, ni en un caché de sesión. `__repr__` redactado, igual que `ChannexClient`.

El refresh token de Beds24 es **de cuenta**, no de propiedad: ADR 0006 lo señala explícitamente y la regla 3 de `steering/security.md` recuerda que una credencial de cuenta concede escritura sobre *todas* sus propiedades. Vive en el entorno, que es el caso que la regla 3 excluye de su obligación de Fernet y que la regla 8 gobierna: en `.env.example` solo el nombre, nunca un valor.

Rejected: cachear el access token en disco para no gastar un canje por ejecución — ahorra una petición y crea un fichero con una credencial viva durante 24 h.

**Esto obliga a enmendar `steering/security.md`.** Su regla 8 enumera los secretos que pueden vivir en el entorno y cierra la lista con *«esas dos y nada más»* (`PMS_API_KEY` y `CHANNEX_API_KEY`). `BEDS24_REFRESH_TOKEN` es la tercera, así que la enumeración se queda falsa el día que este change aterrice si no se toca. Es el mismo movimiento que hizo `channex-staging-adapter` sobre esa misma línea, y por eso el fichero aparece en la tabla de abajo. La enmienda es de una frase: añadir la variable y decir por qué no la gobierna la regla 3 — vive en el entorno, que es justo lo que esa regla excluye — con la nota de que es credencial **de cuenta** y por tanto de radio de daño mayor que una de propiedad.

### D8 — La allowlist de host es una constante del script, no se deriva del entorno

**Chosen:** el script compara el **hostname** de cada URL contra una constante `ALLOWED_HOSTS`, y se niega a emitir la petición si no coincide (R6.5). El literal se fija en implementación contra la especificación OpenAPI 3.0 publicada de la API V2, no se adivina aquí.

Derivar la allowlist de `BEDS24_BASE_URL` la haría inútil —cualquiera que controle el entorno controla el destino, que es justo el ataque del que protege— y comparar subcadenas de la URL deja pasar `api.beds24.com.evil.tld`. Es el mismo criterio que `channex-staging-adapter` aplicó a `staging.channex.io`.

### D9 — Los tests son offline, sin marcador nuevo y sin test dependiente de credenciales

**Chosen:** se prueban las partes puras contra `httpx.MockTransport` y datos en memoria: el anonimizador extraído, la construcción del registro de coste (incluido el caso `X-RequestCost` ausente → `null`), la allowlist de host, el rechazo de credencial vacía, el rechazo de argumentos no reconocidos sin eco de su valor, y el cálculo de latencia y de desorden del sink.

El repo no tiene hoy **ni un solo** `skipif` ni marcador de red; introducir el primero para un test que solo corre con una cuenta de pago haría que CI reportara verde sobre algo que nunca ejecuta. La verificación contra el proveedor real es el propio runbook, y su evidencia es el JSONL commiteado.

Rejected: un marcador `live` con `skipif` sobre la variable de entorno — rompe el precedente y produce cobertura ficticia.

### D10 — El change se entrega en dos mitades, y la segunda es del operador

**Chosen:** el banco (scripts, extracción del anonimizador, tests, runbook, `.env.example`) se construye y se verifica sin red ni credenciales. Las mediciones (R1.1–R1.4, R2.1–R2.5, R3.1, R4.2, R5.1) exigen la cuenta de desarrollo de Beds24, que solo puede dar de alta una persona: trial de 14 días que **arranca al registrarse**, ~€15,50/mes después.

Ese reparto es el que justifica el orden del roadmap. Si el banco no estuviera listo antes de abrir la cuenta, parte de los 14 días se iría en escribirlo — y el motivo declarado de separar esta entrada de `channex-staging-adapter` fue exactamente ese, que los 14 días fueran íntegros a medir.

Consecuencia operativa: este change **no puede alcanzar `READY_FOR_PR` sin la cuenta**, porque sus criterios de aceptación son mediciones. Queda bloqueado con el banco commiteado y la instrucción exacta en `BLOCKED.md`.

### D11 — Sondeo y webhook se unen por el id de reserva, y la latencia se mide sobre el hecho que el sondeo provocó

**Chosen:** los dos registros llevan un campo común, `booking_ref`: el identificador de la reserva de Beds24 sobre la que actúa la petición del sondeo, y el que el sink extrae del payload entrante. La latencia de R2.2 es la diferencia entre `received_at_utc` del sink y el instante del hecho, tomado en este orden:

1. el sello temporal que el propio payload traiga, si lo trae;
2. si no, el `ts_utc` de la línea del sondeo con el mismo `booking_ref` — el sondeo es quien provocó el hecho, así que su instante de respuesta es la cota superior del momento en que ocurrió.

Sin esa clave los dos JSONL son inconexos y R2.2 no tiene forma de calcularse: uno dice «a las 14:02:11 recibí un webhook» y el otro «a las 14:02:03 creé una reserva», y con más de una reserva en vuelo emparejarlos por proximidad temporal es adivinar. Con el `booking_ref` el emparejamiento es exacto, que es además lo que permite responder a R2.4 (si el orden de llegada difiere del orden de los hechos, se ve comparando las dos secuencias).

`booking_ref` es un identificador de negocio y sobrevive a la anonimización por estar en la allowlist de D2 — es justo el caso para el que existe.

Rejected: emparejar por cercanía temporal — falla en cuanto hay dos hechos en la misma ventana, que es precisamente el escenario donde R2.4 quiere medir el desorden.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Scripts | `backend/scripts/beds24_probe.py` | **nuevo** — canje de token (D7), allowlist de host (D8), sondeo con registro de coste (D4), captura anonimizada (D2/D3), subcomando `report` (D5), límite de ritmo propio (R4.3) |
| Scripts | `backend/scripts/beds24_webhook_sink.py` | **nuevo** — receptor sellado en UTC, **anonimización del cuerpo y de las cabeceras antes de escribir** (D6), volcado a JSONL, cálculo de latencia y desorden por `booking_ref` (D11) |
| Scripts | `backend/scripts/anonymise.py` | **nuevo** — anonimizador fail-closed extraído, `business_keys` como parámetro (D2) |
| Scripts | `backend/scripts/channex_probe.py` | **modificado** — importa el módulo extraído; sin cambio de comportamiento |
| Tests | `backend/tests/integrations/test_beds24_probe.py` | **nuevo** — partes puras, `httpx.MockTransport` (D9) |
| Tests | `backend/tests/integrations/test_beds24_webhook_sink.py` | **nuevo** — latencia, desorden, volcado |
| Tests | `backend/tests/integrations/test_channex_probe.py` | **modificado** — importa desde el módulo extraído; la parametrización sobre fixtures se conserva |
| Tests | `backend/tests/integrations/conftest.py` | **modificado** — loader de fixtures de Beds24 junto al de Channex |
| Fixtures | `backend/tests/integrations/fixtures/beds24/*.json` | **nuevo** — reserva y mensaje reales anonimizados (R3.1) |
| Docs | `docs/beds24-spike.md` | **nuevo** — runbook, regla dura de R6.1, hallazgos (marcados *no medido* hasta que se midan) |
| Docs | `docs/beds24-request-cost.jsonl` | **nuevo** — registro crudo de coste como evidencia (D4) |
| Config | `.env.example` | **modificado** — `BEDS24_REFRESH_TOKEN` (solo el nombre) y `BEDS24_BASE_URL` |
| Steering | `sdd/steering/security.md` | **modificado** — regla 8: la enumeración cerrada («esas dos y nada más») pasa a tres con `BEDS24_REFRESH_TOKEN`, anotando que es credencial **de cuenta** (D7) |
| Docs | `docs/README.md` | **modificado** — índice: entrada para `beds24-spike.md`, igual que la que tiene `channex-staging.md` |
| Docs | `README.md` (raíz) | **modificado** si `steering/documentation.md` lo exige para una herramienta nueva |

## Data & interfaces

**Esquema de base de datos**: sin cambios. Ninguna migración. No se escribe en `webhook_events`.

**Contrato de API**: sin cambios. `backend/openapi.json` no se regenera porque no hay endpoint nuevo.

**Dependencias**: ninguna nueva. `httpx` ya es dependencia de runtime; el sink usa `http.server` de la biblioteca estándar.

**Variables de entorno** (solo las leen los scripts; **no** entran en `Settings`):

| Variable | Uso | Default |
|---|---|---|
| `BEDS24_REFRESH_TOKEN` | credencial de cuenta, se canjea por el access token de 24 h | ninguno — falla rápido si falta |
| `BEDS24_BASE_URL` | base de la API V2 | el literal de la spec publicada, fijado en implementación |

**Artefactos en disco**:

- `docs/beds24-request-cost.jsonl` — una línea por petición: `{ts_utc, booking_ref, endpoint, method, shape, x_request_cost, credit_headers, status}`.
- el JSONL del sink — una línea por webhook: `{received_at_utc, booking_ref, method, path, header_names, body}`. `body` va **anonimizado** y `header_names` lleva solo los nombres de las cabeceras, nunca sus valores (D6).
- `backend/tests/integrations/fixtures/beds24/*.json` — payloads anonimizados, con constancia de qué claves se sustituyeron (R3.5).

`booking_ref` es la clave que une los dos primeros y hace calculable la latencia de R2.2 y el desorden de R2.4 (D11).

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **`EXTERNAL_DEPENDENCY`: no hay cuenta de Beds24.** Sin ella no hay medición, y el trial de 14 días arranca al registrarse. | Es el orden que el roadmap eligió: el banco primero, la cuenta después, los 14 días íntegros a medir. El change se bloquea con el banco listo y una sola instrucción para el operador (D10). |
| Extraer el anonimizador regresa los fixtures de Channex. | `test_channex_probe.py` ya parametriza sobre **todos** los fixtures commiteados; la extracción es verde o no es. |
| La allowlist de claves de Beds24 nace incompleta y el fixture queda inservible. | Fail-closed: el error por omisión es sobre-anonimizar, nunca filtrar. Bucle capturar → revisar → ensanchar (D3). |
| El propio sondeo consume la cuota de 100 créditos / 5 min y falsea la medición. | Límite de ritmo configurable con default conservador (R4.3) y parada con espera ante cuota agotada (R4.2). Nunca se busca el techo provocándolo (R4.1). |
| La URL del quick tunnel cambia en cada sesión, así que el webhook hay que reconfigurarlo. | Paso del runbook. Beds24 además **no tiene API de configuración de webhooks** —se configuran por propiedad desde su panel, matiz que `channex-staging-adapter` dejó anotado en su D10—, así que el paso es manual de todas formas. |
| Una medición contradice ADR 0006. | R5.4: se señala como contradicción en `docs/beds24-spike.md` y **no** se enmienda el ADR en este change. |
| El payload de reserva trae datos de titular de tarjeta. | R3.4: se descartan en la captura, no llegan a disco. La cuenta sin canales OTA hace el caso improbable, pero la regla 13 no depende de eso. |

## Open questions

Ninguna. Las dos cosas que este change no puede resolver por sí mismo —el alta de la cuenta y la ejecución de las mediciones— no son decisiones de diseño sino la dependencia externa de D10, y su handoff es `BLOCKED.md`, no una pregunta abierta.
