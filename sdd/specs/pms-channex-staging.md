# PMS Channex (staging)

## Purpose

Segunda implementación del puerto `PMSAdapter`, contra la API real de Channex en su entorno de
staging. Existe para **validar el backend contra un PMS de verdad** en vez de contra un mock que
nosotros escribimos: `ReservationIngestor`, la idempotencia por `(tenant_id, external_pms_id)`, la
persistencia de `TimelineEvent` y el CLI de sync se verifican con payloads que no fabricamos.

**No es el proveedor de producción.** [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md)
elige Beds24 para el MVP y sitúa Channex en fase SaaS. Lo que Channex aporta y ningún otro
proveedor evaluado puede es acceso al entorno de test de Booking.com. Operación, hallazgos medidos
y runbook: [`docs/channex-staging.md`](../../docs/channex-staging.md).

## Requirements

### Transporte y credencial

- THE SYSTEM SHALL autenticarse con la cabecera `user-api-key` y leer su valor de
  `CHANNEX_API_KEY`, que vive **en el entorno y nunca en base de datos** — el caso que la regla 3
  de `steering/security.md` excluye de su obligación de cifrado.
- THE SYSTEM SHALL apuntar por defecto a `https://staging.channex.io/api/v1`, para que un descuido
  de configuración aterrice en staging y nunca en una cuenta viva.
- THE SYSTEM SHALL rechazar una API key vacía al construir el cliente, antes de emitir petición
  alguna.
- THE SYSTEM SHALL no incluir el valor de `user-api-key` en ningún `repr`, log, mensaje de error ni
  traceback formateado.
- WHEN el proveedor responde con error de transporte, `401`, `429` o `5xx`, THE SYSTEM SHALL
  traducirlo a `PmsUnavailableError` — vocabulario del puerto, no de Channex — y no SHALL incluir
  el cuerpo crudo de la respuesta, que puede devolver lo que se envió.

### Paginación

- THE SYSTEM SHALL paginar toda colección hasta agotarla, porque el `limit` por defecto del
  proveedor es **10**.
- WHEN `meta.total` es un entero, THE SYSTEM SHALL detenerse al alcanzarlo.
- WHEN `meta.total` falta y `meta.limit` **difiere** del límite solicitado, THE SYSTEM SHALL tratar
  una página más corta que ese `meta.limit` como la última.
- IF `meta.limit` coincide con el límite solicitado, THEN THE SYSTEM SHALL ignorarlo y paginar hasta
  recibir una página vacía: muchas APIs devuelven ahí el `?limit=` que se pidió, y un eco es
  indistinguible de un tope real del servidor.
- WHEN una página llega vacía, THE SYSTEM SHALL detenerse, cualquiera que sea lo que `total`
  afirme.
- IF se alcanza el tope de páginas configurado, THEN THE SYSTEM SHALL lanzar `PmsUnavailableError`
  en lugar de devolver una lista truncada: dentro de un sync, truncar en silencio es
  indistinguible de «el PMS no tenía más».

### Ventana temporal

- THE SYSTEM SHALL consultar `GET /bookings` filtrando por `filter[inserted_at][gte]`.
- THE SYSTEM SHALL enviar ese instante en **UTC y sin offset**, convirtiendo un `datetime`
  tz-aware y asumiendo UTC en uno naive.
- **Limitación conocida y aceptada**: `/bookings` no ofrece filtro por fecha de modificación, así
  que `list_reservations(since)` ve reservas *creadas* después de `since` y **no** ve una
  modificación ni una cancelación de una anterior. Sirve para validar el backend; no sirve como
  base de un sync de producción. `pms-beds24-adapter` hereda el problema.

### Mapeo a `ReservationDTO`

- THE SYSTEM SHALL usar `unique_id` como `external_id` — el identificador estable entre revisions,
  nunca `revision_id`, `booking_id` ni `system_id`, que son de la revision y romperían la
  idempotencia por `(tenant_id, external_pms_id)`.
- THE SYSTEM SHALL traducir el nombre de OTA del proveedor a `ReservationChannel`, aceptando las
  grafías reales (`BookingCom` sin punto es la que llega de una reserva de verdad), y WHEN no
  reconoce el valor THE SYSTEM SHALL usar `OTHER` en lugar de propagar el literal: `parse` lanza
  ante desconocidos y el ingestor convertiría eso en fila descartada, perdiendo reservas válidas
  cuando entre una OTA nueva.
- THE SYSTEM SHALL traducir `new` y `modified` a `CONFIRMED` y `cancelled` a `CANCELLED`; IF el
  estado no está en esa tabla, THEN THE SYSTEM SHALL propagarlo sin traducir para que la validación
  de dominio lo rechace y la fila se reporte. **Asimetría deliberada frente al canal**: un canal
  mal puesto no mueve nada, un estado mal puesto conduce la `PropertyStateMachine`.
- THE SYSTEM SHALL tratar una comisión de **cero como ausencia de dato, para cualquier OTA**. El
  proveedor nunca envía `null` y devuelve `"0.00"` incluso en una reserva real de Booking.com, que
  siempre cobra comisión: ninguna regla basada en *qué* OTA la envía puede distinguir el cero real
  del dato ausente, y `None` («no lo sabemos») es cierto donde `0` sería una afirmación falsa.
- THE SYSTEM SHALL descartar todo importe no finito o no parseable devolviendo `None`, incluidos
  `NaN` e `Infinity`, que construyen como `Decimal` sin error.
- THE SYSTEM SHALL dejar en `None` todo campo de PRD §16 que el proveedor no aporte, documentándolo
  en el código, y no SHALL inventar un valor — en particular no hay hora de salida.
- THE SYSTEM SHALL conservar en `raw_payload` el elemento del proveedor sin tocar.
- WHEN se consulta una reserva por un id que el proveedor no conoce, THE SYSTEM SHALL devolver
  `None` y no SHALL lanzar, igual que `MockPMSAdapter`: un id ausente es una respuesta, no un
  fallo.

### ⚠️ Datos de titular de tarjeta

- THE SYSTEM SHALL asumir que **toda reserva de OTA llega con un objeto `guarantee`** que contiene
  `card_number`, `card_type`, `cvv`, `cardholder_name` y `expiration_date`, medido contra la API
  real.
- THE SYSTEM SHALL no persistir, loguear ni reenviar ese objeto. Hoy se cumple porque
  `raw_payload` vive solo en memoria y ninguna columna lo almacena; **cualquier change que llegue a
  persistirlo debe descartar los datos de tarjeta en la frontera** — PCI DSS prohíbe retener el
  CVV, así que cifrar no basta.
- THE SYSTEM SHALL mantener desactivadas las opciones VCC del canal (`Allow VCC Updates`,
  `Allow VCC Balance`, `Allow VCC Fees Payout`, `Allow Payout Updates`), que solo ampliarían la
  superficie de datos de pago.

### Fixtures y su anonimización

- THE SYSTEM SHALL versionar los payloads capturados en
  `backend/tests/integrations/fixtures/channex/`, y THE SYSTEM SHALL alimentar con ellos los tests
  del mapeo **sin ninguna llamada de red**, de modo que la suite de CI no dependa de la cuenta de
  staging.
- THE SYSTEM SHALL anonimizar **en el momento de capturar**, no en una pasada manual posterior.
- THE SYSTEM SHALL anonimizar con la política **fail-closed**: una hoja de texto sobrevive solo si
  su clave es dato de negocio reconocido; el resto se sustituye. Esto aplica a las tres posiciones
  donde un valor puede esconderse — hojas de texto, hojas numéricas y **claves de diccionario** — y
  un escalar dentro de una lista se juzga **como si no tuviera nombre**, para que la clave de su
  lista no pueda concederle nada.
- THE SYSTEM SHALL conservar `None` y los booleanos, para que el fixture siga ejercitando la misma
  opcionalidad que el payload real.
- THE SYSTEM SHALL leer la credencial solo del entorno y SHALL rechazar cualquier argumento no
  reconocido **sin imprimir su valor**, que podría ser la propia credencial.

### Provisión del sandbox

- THE SYSTEM SHALL provisionar el sandbox de forma **reproducible e idempotente** por API: una
  segunda ejecución reusa lo existente y no duplica nada.
- THE SYSTEM SHALL instalar únicamente aplicaciones de una **allowlist verificada como gratuita**,
  y no SHALL deducir que una app es gratis porque el catálogo no le declare precio.
- THE SYSTEM SHALL negarse a escribir contra cualquier host que no sea exactamente
  `staging.channex.io` o `secure-staging.channex.io`, comparando el **hostname** y no una subcadena
  de la URL.

## Key files

- `backend/app/integrations/domain/ports.py` — `PMSAdapter`, incluido `unmappable_rows`.
- `backend/app/integrations/domain/errors.py` — `PmsUnavailableError`.
- `backend/app/integrations/infrastructure/channex/client.py` — transporte, paginación,
  traducción de errores y redacción de la credencial.
- `backend/app/integrations/infrastructure/channex/mapping.py` — Channex → `ReservationDTO`.
- `backend/app/integrations/infrastructure/channex/adapter.py` — el puerto, con el filtro UTC y
  el mapeo por elemento.
- `backend/app/integrations/cli/pms_sync.py` — flag `--provider` y códigos de salida.
- `backend/app/core/config.py` — `channex_*` settings.
- `backend/scripts/channex_{probe,bootstrap,claim_test_hotel}.py` — sondeo, provisión y
  adquisición de turno de hotel de test. **Fuera de `app/` y excluidos de la imagen** por
  `backend/.dockerignore`: son herramientas de un solo uso contra un servicio externo.
- `backend/tests/integrations/fixtures/channex/*.json` — payloads reales anonimizados.
- `docs/channex-staging.md` — runbook y hallazgos medidos.
