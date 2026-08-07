# Proposal: pms-beds24-adapter

## Why

El backend sabe hablar con dos PMS, y **ninguno de los dos es el proveedor del MVP**. `MockPMSAdapter` no puede sorprendernos y `ChannexAdapter` es una herramienta de validación de dev cuya única superficie viva —el turno de hotel de test de Booking.com— es una ventana de dos o tres horas en cola. Beds24 es el proveedor que [ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md) eligió para el MVP, ya hay cuenta de desarrollo, y `pms-provider-resolution` dejó el enchufe puesto: `properties.pms_provider` admite `BEDS24`, la credencial de cuenta se guarda cifrada en `pms_credentials` y la factory la resuelve, la descifra y la audita — para acto seguido lanzar `PmsUnavailableError` porque **no hay adapter**. Este change es ese adapter.

Llega con una ventaja que no se repetirá: `pms-beds24-spike` midió el proveedor real antes de diseñar, así que aquí no se supone casi nada. Los hallazgos con carácter normativo están en [`sdd/specs/pms-beds24-spike.md`](../../specs/pms-beds24-spike.md) y el detalle en [`docs/beds24-spike.md`](../../../docs/beds24-spike.md).

Y llega con una deuda de evidencia con dueño: cinco mediciones de coste están **transcritas a mano** en el informe del spike, que su propio R1.5 prohíbe. El banco ya se arregló para poder respaldarlas; falta ejecutarlo.

## What changes

Existirá `Beds24Adapter`, una implementación real de `PMSAdapter` contra la API V2 de Beds24, resuelta por la factory a partir de la credencial de cuenta cifrada que ya vive en `pms_credentials` — sin ninguna variable de entorno nueva y sin fallback al mock. Sincronizará la **ventana completa** (creadas, modificadas y canceladas desde `since`), llevará la contabilidad de créditos que el proveedor factura de forma dinámica, y no se fiará del código HTTP para saber si el proveedor aceptó algo. El descarte de datos de titular de tarjeta pasará de cumplirse *por omisión* a cumplirse *por un scrubber*, en los dos adapters que mapean payloads de proveedor. Y las cinco filas transcritas del informe de coste pasarán a estar respaldadas por el registro commiteado.

Después de este change, un sync programado contra Beds24 es posible; hoy no lo es.

## Requirements

### R1 — Transporte autenticado, con la credencial que ya está guardada

**Como** operador, **quiero** que el adapter de producción hable con Beds24 usando la credencial de cuenta cifrada que el CLI de credenciales aprovisiona, **para que** no aparezca una segunda vía de credencial fuera de la regla 3 y la rotación siga teniendo un solo sitio.

Criterios de aceptación:

1. WHEN la factory resuelve una propiedad cuyo proveedor es `BEDS24`, THE SYSTEM SHALL construir el adapter con el secreto descifrado que ya obtiene de `pms_credentials` (scope `ACCOUNT`), y NOT SHALL leer ninguna variable de entorno de credencial de Beds24.
2. WHERE el adapter necesita un access token, THE SYSTEM SHALL canjearlo desde el refresh token y mantenerlo **solo en memoria**, nunca en disco ni en base de datos. El refresh token **no rota** al usarse (medido), así que no hay escritura de vuelta que perder.
3. THE SYSTEM SHALL exigir esquema `https` y comparar el **hostname exacto** de cada URL contra una allowlist **constante**, nunca contra una subcadena y nunca derivada de configuración: el secreto es credencial de cuenta y concede escritura sobre todas las propiedades de esa cuenta.
4. THE SYSTEM SHALL no incluir el valor del refresh token ni del access token en ningún `repr`, log, mensaje de error o traceback, **incluida su forma escapada**, con un test que lo demuestre.
5. IF el canje devuelve un refresh token distinto al enviado, THEN THE SYSTEM SHALL fallar de forma ruidosa **sin imprimir el valor** — el hallazgo dice que no rota, y una rotación silenciosa perdida bloquea la cuenta a los 30 días.
6. WHEN un sync resuelve N propiedades del mismo grupo de proveedor, THE SYSTEM SHALL realizar **como máximo un canje de token por ejecución y cuenta**, no uno por propiedad ni uno por resolución.

### R2 — `list_reservations` con la ventana completa, demostrada

**Como** gestor, **quiero** que un sync vea también lo que cambió y lo que se canceló, **para que** el estado del sistema no diverja del PMS en cuanto un huésped modifica o anula.

Criterios de aceptación:

1. WHEN se invoca `list_reservations(since)`, THE SYSTEM SHALL devolver las reservas **creadas, modificadas y canceladas** desde `since`, y no solo las creadas.
2. THE SYSTEM SHALL demostrarlo con un ciclo crear → modificar → cancelar ejecutado contra la cuenta de desarrollo por `beds24_probe.py provoke`, dejando el payload de cada estado como fixture anonimizado y versionado.
3. WHEN se invoca con `property_external_id`, THE SYSTEM SHALL acotar la consulta a esa propiedad del proveedor.
4. WHEN el adapter no sabe mapear un elemento, THE SYSTEM SHALL devolverlo como fila no mapeable dentro del `PmsFetchResult` junto a las que sí mapeó, nunca descartándolo en silencio ni abortando la página entera.
5. WHEN se invoca `get_reservation(external_id)` con un id que el proveedor no conoce, THE SYSTEM SHALL devolver `None`, y no SHALL confundirlo con un fallo de transporte.
6. THE SYSTEM SHALL alimentar los tests del mapeo con los fixtures versionados y **sin ninguna llamada de red**.

### R3 — Créditos y veredicto: ni el presupuesto ni el éxito se suponen

**Como** operador, **quiero** que el adapter mida lo que gasta y compruebe lo que el proveedor realmente hizo, **para que** un sync no agote la cuota de la cuenta ni informe de un éxito que no ocurrió.

Criterios de aceptación:

1. WHEN una respuesta trae la cabecera de coste, THE SYSTEM SHALL leerla por su nombre real `x-request-cost` (con guiones) y tratarla como **decimal**; WHEN no la trae, THE SYSTEM SHALL registrar «desconocido» y **nunca `0`**.
2. IF el proveedor señala cuota agotada, THEN THE SYSTEM SHALL detenerse y propagar `PmsUnavailableError` —que el CLI ya traduce a código de salida 3—, y no SHALL reintentar en bucle ni devolver una lista vacía indistinguible de un PMS sin datos.
3. THE SYSTEM SHALL determinar si el proveedor aceptó una petición **por el cuerpo de la respuesta y no por el código HTTP**, cubriendo las cuatro formas medidas (éxito con `new`, rechazo por elemento con `errors` y `success: false` bajo HTTP `201`, y petición malformada devuelta como objeto en vez de lista).
4. THE SYSTEM SHALL declarar en el código el presupuesto medido como un **techo impuesto por la cuota y no como cadencia recomendada**, citando la spec en vez de reformular la cifra.

   > **Nota del 2026-08-06**: este criterio llevaba la cifra escrita —«8 créditos por ciclo»— mientras exigía no reformularla, y al medirse pasó a **10 créditos / 30 s** porque el catálogo incluye ahora la consulta que el sync hace de verdad. Se retira el número del criterio, que es lo que el criterio pedía en primer lugar; la ventana de 100 créditos / 300 s por cuenta sigue siendo del proveedor y no cambia. El valor vive en `docs/beds24-spike.md`, generado desde el registro.

### R4 — Datos de tarjeta: descartados por un scrubber, no por omisión

**Como** responsable del cumplimiento, **quiero** que los datos de titular de tarjeta se eliminen en la frontera del adapter, **para que** ningún change posterior que persista un payload los meta en la base de datos.

Criterios de aceptación:

1. WHEN un adapter de PMS mapea un elemento del proveedor a `ReservationDTO`, THE SYSTEM SHALL eliminar los campos con forma de dato de tarjeta o de credencial de pago —incluidos `guarantee` y equivalentes de Channex y `stripeToken`/`pcibookingToken` de Beds24— **antes** de que el elemento entre en el DTO, incluido `raw_payload`.
2. THE SYSTEM SHALL aplicar ese descarte **también en `ChannexAdapter`**, cuyo mapeo hoy mete el elemento del proveedor entero y sin tocar, con un test que lo fija así (`test_channex_mapping.py`): la regla 13 se cumple hoy por omisión —ningún consumidor lee `raw_payload` y ninguna columna lo almacena— y esa omisión no es una garantía.
3. THE SYSTEM SHALL descartar, y no cifrar: un adapter que traiga estos datos a memoria y los deje morir ahí cumple; uno que los guarde «cifrados» no (PCI DSS prohíbe retener el CVV).
4. THE SYSTEM SHALL mantener el guard automático que comprueba que **ningún fixture commiteado**, de cualquier proveedor, contiene datos con forma de tarjeta, cubriendo los fixtures nuevos que este change añada.

### R5 — La factory resuelve Beds24 de verdad

**Como** desarrollador, **quiero** que la resolución por propiedad deje de ser un camino que siempre falla para Beds24, **para que** el trabajo de `pms-provider-resolution` tenga su primer consumidor real.

Criterios de aceptación:

1. WHEN la factory resuelve una propiedad `BEDS24` con credencial guardada y válida, THE SYSTEM SHALL devolver el `Beds24Adapter` en lugar de lanzar `PmsUnavailableError`.
2. IF la credencial falta, THEN THE SYSTEM SHALL seguir lanzando `MissingPmsCredentialError`; IF no descifra, THEN `SecretDecryptionError`. En ningún caso SHALL caer al mock.
3. WHEN un sync agrupa las propiedades de un tenant por proveedor, THE SYSTEM SHALL hacer **una llamada por proveedor distinto** también para Beds24, cuya credencial es de cuenta, y SHALL restringir el emparejamiento de reservas al grupo de su proveedor.
4. WHEN una resolución automática descifra la credencial de Beds24, THE SYSTEM SHALL registrarla con la granularidad que fija la entrada nombrada de la regla 9 de `steering/security.md`, sin reformularla.
5. THE SYSTEM SHALL verificar el adapter contra la conformidad estructural del puerto por test (`vars(Port)` + `callable(...)`), como el repositorio ya hace con los otros dos.

### R6 — Las cinco mediciones transcritas pasan a estar respaldadas

**Como** lector del informe de coste, **quiero** que ninguna cifra publicada sea una transcripción, **para que** el presupuesto de créditos se derive de datos revisables como exige el propio contrato del spike.

Criterios de aceptación:

1. THE SYSTEM SHALL re-ejecutar `capture` y `provoke` contra la cuenta de desarrollo y commitear el `docs/beds24-request-cost.jsonl` resultante, de modo que las cinco filas hoy transcritas —`GET /bookings/messages` y los cuatro `POST`— queden respaldadas por el registro.
2. THE SYSTEM SHALL regenerar la tabla del informe **desde el registro** con `beds24_probe.py report`, y no SHALL transcribirla a mano.
3. WHEN el coste fraccionario de `modify` y `cancel` se confirme o se desmienta, THE SYSTEM SHALL actualizar el informe en consecuencia: hoy el `1,1` es la única observación de un coste no entero y es transcrita.
4. THE SYSTEM SHALL retirar del informe el aviso de «evidencia de peor calidad» solo para las filas que hayan quedado respaldadas, y SHALL mantenerlo para lo que siga sin medirse.

## Out of scope

- **Toda la mensajería y `PMSMessagingPort`** → `beds24-messaging-adapter` (entrada nueva, creada al abrir este proposal). Sin canales conectados, `GET /bookings/messages` llega vacío y el `POST` solo funciona sobre reservas de OTA: se puede escribir, no se puede validar. Consecuencia: **este change es enteramente de lectura**, así que el hallazgo del `201` (R3.3) se implementa y se prueba sobre las respuestas que el adapter sí recibe, pero su consumidor de escritura nace allí.
- **Conectar cualquier canal OTA** a la cuenta de Beds24, y con ello la medición de latencia, orden y llegada de la cabecera estática de los webhooks → `beds24-webhook-cutover-measurement`. La regla dura de aislamiento de la cuenta sigue vigente.
- **El endpoint de recepción de webhooks y la regla 12** de `steering/security.md` → `reservations-webhooks`.
- **El port split, la factory y las columnas de credencial** con sus cinco obligaciones → ya entregados por `pms-provider-resolution`; aquí se consumen, no se rediseñan.
- **Las operaciones de ARI** (`update_price`, `block_dates`, `get_availability`) y `list_properties`: llegan con el change que las consume (`revenue`), como declara `domain/ports.py`.
- **El mapeo de propiedades a Booking.com**, que el proveedor no expone por API (*"Mapping to booking.com cannot be done via our API"*) y lleva un paso humano en su panel.
- **Retrofitar el cifrado** de `properties.wifi_password_encrypted` y `guests.document_number_encrypted`, deuda con dueño propio heredada de `domain-foundation-core`.
- **La capa de accesos** (TTLock/Nuki, Arrivals API), aplazada a propósito en la decisión 5 de ADR 0006.

## Affected specs

- `sdd/specs/pms-beds24-adapter.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/pms-provider-resolution.md` — deja de ser cierto que resolver `BEDS24` termine en `PmsUnavailableError`.
- `sdd/specs/pms-beds24-spike.md` — sus hallazgos normativos pasan a tener consumidor, y las cinco mediciones transcritas cambian de categoría (R6).
- `sdd/specs/pms-channex-staging.md` — el mapeo pasa por el scrubber de la regla 13, lo que cambia el contrato que su spec fija hoy (R4.2).

**Steering que se cita y no se reformula**: regla 3 (credenciales de proveedor), regla 9 (granularidad de auditoría de lecturas automáticas) y regla 13 (datos de titular de tarjeta) de `sdd/steering/security.md`. La regla 13 se aplica **en fase de diseño**, como ella misma exige.
