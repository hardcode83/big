# Tasks: pms-beds24-spike

Las secciones 1-6 construyen el banco de medición y se verifican **sin red y sin credenciales**.
La sección 7 son las mediciones contra la cuenta real de Beds24 y depende de un
`EXTERNAL_DEPENDENCY` que solo puede resolver una persona (ver D10 y `BLOCKED.md`).

## 1. Extracción del anonimizador <!-- panel: PASS 2026-08-03 -->

Va primero porque toca código existente y probado: si rompe algo, se ve antes de construir nada encima.

- [x] 1.1 Crear `backend/scripts/anonymise.py` moviendo `anonymise`, `_anonymise_value`, `_anonymise_key`, `_anonymise_leaf` y las seis piezas de política desde `backend/scripts/channex_probe.py`. Solo `PRESERVED_KEYS` se parametriza (`business_keys: frozenset[str]`); `PRESERVED_SUFFIXES`, `PII_PLACEHOLDERS`, `_IDENTIFIER_KEY`, `_DATE_KEY` e `IDENTIFYING_NUMBER_FLOOR` quedan como constantes compartidas. **El orden se conserva**: las agujas de PII corren antes que `PRESERVED_SUFFIXES`. [R3]
- [x] 1.2 `backend/scripts/channex_probe.py` importa del módulo extraído y le pasa su `PRESERVED_KEYS`. Sin cambio de comportamiento. [R3]
- [x] 1.3 `backend/tests/integrations/test_channex_probe.py` sigue verde tal cual, incluida su parametrización sobre `sorted(FIXTURE_DIR.glob("*.json"))`. Añadir en `test_anonymise.py` un test que fije el invariante de orden: una clave `expiration_date` **no** sobrevive pese a terminar en un sufijo preservado. [R3]

## 2. Transporte, credencial y frenos del sondeo <!-- panel: PASS 2026-08-03 -->

- [x] 2.1 `backend/scripts/beds24_probe.py`: lee `BEDS24_REFRESH_TOKEN` del entorno, lo canja por el access token de 24 h, lo mantiene **solo en memoria**. `__repr__` redactado. Tests con `httpx.MockTransport`: canje correcto, y ni el refresh ni el access aparecen en `repr`, logs ni excepciones. [R6.4]
- [x] 2.2 Rechazo de credencial ausente o vacía **antes de emitir petición alguna**, nombrando la variable. Test. [R6.3]
- [x] 2.3 Constante `ALLOWED_HOSTS` con el hostname de la API V2 tomado de su OpenAPI 3.0 publicada; comparación por **hostname exacto**, no por subcadena. Tests: host válido pasa, `api.beds24.com.evil.tld` se rechaza, una subcadena en el path no cuela. [R6.5]
- [x] 2.4 Rechazo de argumentos no reconocidos **sin imprimir su valor**. Test que afirma que el valor no aparece en la salida. [R6.6]
- [x] 2.5 Límite de ritmo propio configurable con default conservador, y parada con espera a la siguiente ventana cuando la respuesta indica cuota agotada (nunca reintento inmediato). Tests sobre reloj inyectado. [R4.2, R4.3]

## 3. Registro de coste por petición <!-- panel: PASS 2026-08-03 -->

- [x] 3.1 Construcción del registro con el esquema de D4/D11: `{ts_utc, booking_ref, endpoint, method, shape, x_request_cost, credit_headers, status}`. Tests: `X-RequestCost` presente se registra; **ausente se registra `null`, nunca `0`**; las cabeceras de crédito restante que vengan se capturan. [R1.1, R1.3, R1.4]
- [x] 3.2 Escritura JSONL en la ruta de `--out`, una línea por petición. Test sobre `tmp_path`. [R1.5]
- [x] 3.3 Catálogo de peticiones a sondear: cada endpoint que el sync de `celery-jobs` va a usar, con **al menos dos formas** en el eje que se sospecha que mueve el coste (tamaño de página, amplitud del rango de fechas, número de propiedades). Test que afirma que ningún endpoint del catálogo queda con una sola forma. [R1.2]

## 4. Captura de fixtures <!-- panel: PASS 2026-08-03 -->

- [x] 4.1 Subcomando de captura que anonimiza **en el momento** con la allowlist inicial de Beds24, y deja constancia en el fichero de qué claves se sustituyeron. Tests sobre payloads sintéticos. [R3.1, R3.2, R3.5]
- [x] 4.2 Conservación de `None` y de los booleanos a través de la anonimización. Test. [R3.3]
- [x] 4.3 Descarte de datos de titular de tarjeta en la captura, antes de disco: nada con forma de tarjeta llega al fichero. Test que afirma que ni `card_number`, ni `cvv`, ni `expiration_date` sobreviven. [R3.4]
- [x] 4.4 Loader `beds24_fixture(name)` en `backend/tests/integrations/conftest.py` junto al de Channex, y test parametrizado sobre `fixtures/beds24/*.json` que afirma que **todo fixture commiteado está limpio** — el mismo contrato que tiene Channex. [R3.1]

## 5. Receptor de webhooks <!-- panel: PASS 2026-08-03 -->

- [x] 5.1 `backend/scripts/beds24_webhook_sink.py`: servidor mínimo sobre `http.server` que sella cada petición con el instante UTC de recepción. **El cuerpo pasa por el anonimizador y las cabeceras también**: se persiste `header_names` (nombres, nunca valores) y `body` anonimizado. Tests: un cuerpo con datos de tarjeta no deja rastro en el JSONL; el valor de la cabecera estática de autenticación tampoco. [R2.1, R2.5]
- [x] 5.2 Cálculo de latencia por `booking_ref` con la regla de dos pasos de D11: sello del propio payload si lo trae, si no el `ts_utc` de la línea del sondeo con el mismo `booking_ref`. Tests para ambas ramas y para el caso sin correlación posible. [R2.2]
- [x] 5.3 Detección de desorden comparando la secuencia de llegada con la secuencia de hechos. Test con dos eventos invertidos. [R2.4]

## 6. Informe, configuración y documentación <!-- panel: PASS 2026-08-03 -->

- [x] 6.1 Subcomando `report` de `beds24_probe.py`: lee el JSONL y renderiza la tabla de coste por endpoint y forma, más la **cadencia máxima sostenible** derivada del coste del ciclo completo contra la ventana de 100 créditos / 5 min. Tests sobre un JSONL sintético, incluido el caso con costes `null` (que no pueden sumarse y deben reportarse como tales). [R4.1, R4.4]
- [x] 6.2 `docs/beds24-spike.md`: runbook (alta de la cuenta, canje de credencial, levantar el quick tunnel, configurar el webhook **a mano en el panel de Beds24** porque no hay API para ello, correr sondeo y captura), la **regla dura** de que la cuenta no lleva ningún canal OTA conectado, y la sección de hallazgos con cada medida marcada *no medido*. [R5.1, R5.2, R6.1]
- [x] 6.3 En ese mismo documento, responder explícitamente a la pregunta que `reservations-webhooks` arrastra: Beds24 **no** firma sus webhooks, solo ofrece una cabecera estática, y eso convierte «valida la firma» en «trata todo webhook como aviso no fiable y re-lee por API». [R5.3]
- [x] 6.4 `.env.example`: bloque `BEDS24_REFRESH_TOKEN` (solo el nombre, nunca un valor) y `BEDS24_BASE_URL`, con el estilo del bloque de Channex y la nota de por qué no lo gobierna la regla 3. [R6.2]
- [x] 6.5 `sdd/steering/security.md` regla 8: la enumeración cerrada («esas dos y nada más») pasa a tres, anotando que `BEDS24_REFRESH_TOKEN` es credencial **de cuenta** y por tanto de radio de daño mayor que una de propiedad. [R6.2]
- [x] 6.6 `docs/README.md`: entrada de índice para `beds24-spike.md`, igual que la de `channex-staging.md`. Actualizar el `README.md` de raíz solo si `steering/documentation.md` lo exige por la herramienta nueva. [R5.1]

## 7. Mediciones contra la cuenta real — `EXTERNAL_DEPENDENCY`

Requiere una cuenta de desarrollo de Beds24 y `BEDS24_REFRESH_TOKEN` exportado.
Bloqueadas hasta entonces; ver `BLOCKED.md`.

- [x] 7.1 Correr el sondeo sobre el catálogo de 3.3 y obtener `X-RequestCost` real por endpoint y forma. Commitear el JSONL como `docs/beds24-request-cost.jsonl`. [R1.1, R1.2, R1.3, R1.4]
- [x] 7.2 (parcial: reserva sí, **mensaje no** — `/bookings/messages` llega vacío, no hay conversación sin canal) Capturar una reserva y un mensaje reales, revisar el fichero, **ensanchar la allowlist** de claves de negocio y recapturar hasta que el fixture sea útil sin filtrar nada. Commitear en `fixtures/beds24/`. [R3.1, R3.5]
- [x] 7.3 **Banco ejecutado; valores trasladados a `pms-beds24-adapter`.** Sink, túnel y webhook configurado por API, camino verificado en 246 ms. Tres eventos reales → cero webhooks: Beds24 solo los dispara para reservas de canal y R6.1 los prohíbe aquí. Confirmado en el panel que no falta habilitar nada. R2 enmendado en `proposal.md`; la medición va a la ventana de corte del adapter. [R2.1, R2.5]
- [x] 7.4 Generar el informe con `report`, volcarlo en `docs/beds24-spike.md` y sustituir cada *no medido* por su valor; lo que siga sin medirse se queda marcado como tal. [R4.1, R4.4, R5.1, R5.2]
- [x] 7.5 Contrastar lo medido con lo que afirma ADR 0006 y **señalar toda contradicción** en el documento, sin enmendar el ADR en este change. [R5.4]

## 8. Verification

- [x] 8.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest` (con el stack parado: `docker compose run --rm backend uv run pytest`).
- [x] 8.2 Los fixtures de Channex siguen limpios y sus tests pasan sin modificación de comportamiento tras la extracción de la sección 1.
- [x] 8.3 `grep` sobre los artefactos commiteados (`docs/beds24-request-cost.jsonl`, `fixtures/beds24/*.json`, el JSONL del sink) confirmando que no contienen el refresh token, el access token, el valor de la cabecera estática ni nada con forma de tarjeta.
- [x] 8.4 Los scripts nuevos no viajan en la imagen: verificar que `backend/.dockerignore` los excluye, igual que a los de Channex.
