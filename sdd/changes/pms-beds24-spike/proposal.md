# Proposal: pms-beds24-spike

## Why

[ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md) elige **Beds24** como proveedor PMS/Channel Manager del MVP, pero deja tres cosas explícitamente sin resolver porque **no se pueden resolver leyendo documentación**. La más cara es el coste por petición: Beds24 factura en **créditos con coste dinámico y no publicado**, 100 por 5 minutos y **por cuenta**, y su propia documentación desaconseja el uso en tiempo real recomendando sincronización completa cada ~6 h. La cadencia del scheduler de `celery-jobs` es una función de ese presupuesto, y ese presupuesto hay que **medirlo** (ADR 0006, riesgo *«Que el coste real de créditos de Beds24 haga inviable la cadencia que necesita `messaging-ai`»*, cuya mitigación literal es *«se mide en la primera semana de la cuenta de desarrollo»*).

El change anterior, `channex-staging-adapter`, cerró la lista de lo que falta y dejó dicho que **no se extrapola** (`docs/channex-staging.md` §*«Lo que queda por medir en Beds24»*): `X-RequestCost` por endpoint, latencia real de sus webhooks, payloads reales de reserva y de mensaje, y su límite de tasa. Ese reparto es una cuestión de relojes: el staging de Channex es gratis y sin caducidad, así que aprender el modelo de datos de un PMS se hizo allí; el **trial de 14 días de Beds24 empieza a contar al registrarse** (~€15,50/mes después) y va íntegro a medir.

El entregable de este change **no es código de producto**: es la entrada de diseño de `celery-jobs`, `reservations-webhooks` y `pms-beds24-adapter`. Se hace contra una cuenta de desarrollo real **sin ningún canal OTA conectado**, así que no toca Airbnb ni Booking.com y no pone en riesgo los dos anuncios reales (REDES11, PAJARITOS8).

## What changes

Existirá un **banco de medición de Beds24** que hoy no existe: un script de sondeo fuera de `app/` (misma categoría que `backend/scripts/channex_probe.py` — herramienta de un solo uso contra un servicio externo, excluida de la imagen), un receptor local de webhooks para cronometrar su latencia, un corpus de **payloads reales anonimizados** versionados como fixtures, y un documento de hallazgos `docs/beds24-spike.md` que publica el **presupuesto de créditos derivado** en la forma que `celery-jobs` necesita consumir: peticiones por ciclo de sync y cadencia máxima sostenible por cuenta.

El change tiene **dos mitades con dueños distintos**, y conviene decirlo por adelantado porque determina qué puede completarse sin intervención humana:

- **El banco** (scripts, anonimizador, esquema del informe, tests) se construye y se verifica **sin red y sin credenciales**, contra respuestas grabadas.
- **Las mediciones** exigen una cuenta de desarrollo de Beds24 que solo puede dar de alta una persona (tarjeta, trial que arranca al registrarse). Es un `EXTERNAL_DEPENDENCY` en el sentido de `project.md`: el banco queda listo y ejecutable, y el operador lo corre en su ventana de 14 días.

No se escribe `Beds24Adapter`, ni `PMSAdapterFactory`, ni se añade ninguna `beds24_*` a `app/core/config.py`: no hay código de producto que las consuma todavía.

## Requirements

### R1 — Coste en créditos por endpoint y por forma de petición

**As a** diseñador de `celery-jobs`, **I want** el coste real en créditos de cada llamada que el sync va a hacer, **so that** la cadencia del scheduler se calcule sobre medición y no sobre un supuesto.

Acceptance criteria:

1. WHEN el sondeo ejecuta una petición contra la API de Beds24, THE SYSTEM SHALL registrar el valor de la cabecera `X-RequestCost` junto al endpoint, el método, los parámetros que caracterizan la forma de la petición (tamaño de página, rango de fechas, número de propiedades) y el instante UTC.
2. THE SYSTEM SHALL medir cada endpoint con **al menos dos formas de petición distintas** en el eje que se sospecha que mueve el coste, para que el resultado distinga un coste fijo de uno proporcional.
3. WHEN Beds24 no devuelve `X-RequestCost` en una respuesta, THE SYSTEM SHALL registrar la ausencia como tal y no SHALL sustituirla por cero ni por un valor estimado.
4. THE SYSTEM SHALL registrar también las cabeceras de crédito restante que la respuesta traiga, para poder contrastar el coste declarado con el consumo observado.
5. THE SYSTEM SHALL emitir los resultados como un artefacto estructurado en disco, no solo como salida por pantalla, para que el informe se derive de datos y no de una transcripción.

### R2 — Latencia real de los webhooks

**As a** diseñador de `reservations-webhooks`, **I want** la latencia medida entre el hecho y la llegada de su webhook, **so that** la ventana de re-lectura por API se dimensione con un número propio en vez del «~1 minuto de media» que dice la documentación.

Acceptance criteria:

1. THE SYSTEM SHALL disponer de un receptor de webhooks que registre, por cada petición entrante, el instante UTC de recepción, el método, la ruta, las cabeceras y el cuerpo.
2. WHEN llega un webhook, THE SYSTEM SHALL calcular su latencia como la diferencia entre el instante de recepción y el instante del hecho que lo origina, tomando ese instante del propio payload cuando lo traiga y del registro del sondeo que provocó el hecho cuando no.
3. THE SYSTEM SHALL medir **al menos tres eventos** y publicar los valores individuales, y no SHALL presentar una medición única como una distribución.
4. THE SYSTEM SHALL registrar si los webhooks llegan **desordenados** respecto al orden de los hechos que los originan, porque ADR 0006 afirma que el proveedor no garantiza el orden y `reservations-webhooks` depende de ello.
5. THE SYSTEM SHALL registrar la cabecera estática configurada como único mecanismo de autenticación, confirmando por medición lo que ADR 0006 afirma: que no hay firma HMAC ni secreto negociado.

### R3 — Payloads reales capturados como fixtures anonimizados

**As a** implementador de `pms-beds24-adapter`, **I want** payloads de reserva y de mensaje que no hayamos fabricado nosotros, **so that** el mapeo a `ReservationDTO` se escriba contra la forma real y no contra la documentación del proveedor.

Acceptance criteria:

1. THE SYSTEM SHALL versionar los payloads capturados bajo `backend/tests/integrations/fixtures/beds24/`, cubriendo al menos una reserva y un mensaje.
2. THE SYSTEM SHALL anonimizar **en el momento de capturar**, no en una pasada manual posterior, con la misma política **fail-closed** que `channex-staging-adapter` estableció: una hoja de texto sobrevive solo si su clave es dato de negocio reconocido, y esto aplica a hojas de texto, hojas numéricas y **claves de diccionario**, juzgando un escalar dentro de una lista **como si no tuviera nombre**.
3. THE SYSTEM SHALL conservar `None` y los booleanos, para que el fixture ejercite la misma opcionalidad que el payload real.
4. IF el payload contiene datos de titular de tarjeta, THEN THE SYSTEM SHALL descartarlos en la captura y no SHALL escribirlos en el fixture, aplicando la regla 13 de `steering/security.md` — PCI DSS prohíbe retener el CVV, así que anonimizar no basta y el campo no llega a disco.
5. THE SYSTEM SHALL dejar constancia en el fixture de qué claves fueron sustituidas, para que quien lea el mapeo distinga un valor real de uno anonimizado.

### R4 — Techo de créditos, observado sin provocarlo

**As a** responsable de la cuenta, **I want** saber cuánto margen deja el límite de 100 créditos por 5 minutos, **so that** el sync se diseñe con holgura conocida sin haber roto la cuenta para averiguarlo.

Acceptance criteria:

1. THE SYSTEM SHALL derivar el consumo de un ciclo de sync completo **sumando los costes medidos en R1**, y no SHALL agotar la cuota deliberadamente para encontrar el techo.
2. WHEN una respuesta indica que la cuota se ha agotado, THE SYSTEM SHALL detener el sondeo, registrar el hecho con su instante y esperar a la siguiente ventana en lugar de reintentar de inmediato.
3. THE SYSTEM SHALL limitar su propio ritmo de peticiones a un valor configurable, con un default conservador, para que una ejecución accidental no consuma la ventana de otro.
4. THE SYSTEM SHALL publicar la **cadencia máxima sostenible** que se deduce del coste por ciclo y de la ventana de 100 créditos / 5 min, expresada en la unidad que `celery-jobs` necesita: intervalo mínimo entre syncs por cuenta.

### R5 — El informe como entrada de diseño

**As a** autor de los tres changes que dependen de esto, **I want** un documento que responda a las preguntas abiertas de ADR 0006 con números medidos y con la fecha en que se midieron, **so that** el diseño siguiente cite evidencia y no documentación de proveedor.

Acceptance criteria:

1. THE SYSTEM SHALL publicar `docs/beds24-spike.md` con, como mínimo: cómo se dio de alta la cuenta, qué se midió, cuándo, con qué versión de la API, y el presupuesto de créditos derivado.
2. THE SYSTEM SHALL marcar como **no medido** todo lo que no se haya llegado a medir, en vez de omitirlo — mismo contrato que `docs/channex-staging.md`, donde el límite de tasa figura explícitamente como no medido.
3. THE SYSTEM SHALL responder explícitamente a la pregunta que `reservations-webhooks` arrastra en su enunciado — *«validando firma HMAC cuando el provider la soporte»* — dejando por escrito que Beds24 no la soporta y qué arquitectura implica eso.
4. WHERE una medición contradiga lo que ADR 0006 afirma, THE SYSTEM SHALL señalarlo como contradicción y no SHALL corregir el ADR en este change.

### R6 — La cuenta de desarrollo no toca ninguna OTA, y su credencial no se filtra

**As a** propietaria de dos anuncios reales, **I want** garantía de que el spike no puede alcanzar Airbnb ni Booking.com, **so that** medir un PMS nuevo no arriesgue las reservas vivas.

Acceptance criteria:

1. THE SYSTEM SHALL operar contra una cuenta **sin ningún canal OTA conectado**, y el documento de hallazgos SHALL declararlo como regla dura de la misma forma que `docs/channex-staging.md` §*«Regla dura: qué no se conecta nunca»*.
2. THE SYSTEM SHALL leer la credencial **solo del entorno**, y `.env.example` SHALL llevar únicamente el nombre de la variable, nunca un valor (regla 8 de `steering/security.md`).
3. THE SYSTEM SHALL rechazar una credencial vacía o ausente antes de emitir petición alguna.
4. THE SYSTEM SHALL no incluir el valor de la credencial —ni el refresh token, que ADR 0006 señala como **de cuenta** y por tanto con escritura sobre todas sus propiedades— en ningún `repr`, log, mensaje de error, traceback ni artefacto escrito en disco.
5. THE SYSTEM SHALL negarse a emitir peticiones contra cualquier host que no sea el de la API de Beds24, comparando el **hostname** y no una subcadena de la URL.
6. THE SYSTEM SHALL rechazar cualquier argumento no reconocido **sin imprimir su valor**, que podría ser la propia credencial.

## Out of scope

- **`Beds24Adapter` y su mapeo a `ReservationDTO`** — es `pms-beds24-adapter`. Aquí se capturan los payloads que ese change necesita, no se escribe el mapeo.
- **`PMSAdapterFactory` y la resolución de proveedor por propiedad** (ADR 0006 decisión 7) — también `pms-beds24-adapter`, que además hereda las cinco obligaciones de credenciales que el ADR le asigna.
- **Credenciales de PMS por propiedad en base de datos, cifradas con Fernet** — la credencial de este spike vive en el entorno, que es el caso que la regla 3 de `steering/security.md` excluye.
- **`beds24_*` en `app/core/config.py`** — no hay código de producto que las lea; añadirlas ahora sería configuración muerta.
- **El endpoint de webhooks de producción** —`POST /api/v1/webhooks/{provider}/{webhook_token}`, la forma con token opaco por tenant que ADR 0006 impuso sobre el `POST /api/v1/webhooks/{provider}` de PRD §23— y sus cuatro obligaciones de la regla 12 de `steering/security.md`: es `reservations-webhooks`. Aquí el receptor es una herramienta de medición local y efímera, no una superficie pública permanente, y no escribe en `webhook_events`.
- **Conectar cualquier canal OTA**, mapear Booking.com (que ADR 0006 documenta como imposible por API) y probar la Arrivals API de accesos — la capa de accesos está aplazada por decisión 5 del ADR.
- **Cambiar ADR 0006** aunque una medición lo contradiga: R5.4 obliga a señalarlo, no a enmendarlo.
- **Buscar el techo del límite de tasa provocándolo** — R4.1 lo prohíbe explícitamente.

## Affected specs

- `sdd/specs/pms-beds24-spike.md` — *(no existe aún — se creará al archivar)*. El comportamiento del banco de medición y los hallazgos con carácter normativo para los changes que dependen de él.
