# Proposal: channex-validation-limits

## Why

Dos documentos afirman **en presente** que el sandbox de Channex es un banco de pruebas del
backend contra un PMS real:

- `sdd/specs/pms-channex-staging.md` §Purpose — *«Existe para **validar el backend contra un PMS
  de verdad** en vez de contra un mock que nosotros escribimos»*.
- `sdd/steering/product.md` línea 11 — *«su entorno de staging **ya se usa hoy** como banco de
  pruebas del backend contra un PMS real»*.

Operativamente eso no se sostiene **como capacidad permanente**, y el propio repo tiene medida la
razón. `docs/channex-staging.md` documenta que los hoteles de test de Booking.com son *«un pool
con reserva por franjas horarias, no recursos a demanda»*: el 2026-08-03 los **ocho** IDs
figuraban simultáneamente en uso, la comprobación de unicidad es **global entre cuentas** —a la
hora exacta en que uno se liberaba, otro integrador ya se lo había llevado—, **no hay cola ni
reserva de turno**, y algunos IDs ni aceptan reservas (`10745030` lleva el aviso
`Bookings not possible currently for this ID`, que solo aparece en la ficha por hotel y no en la
lista resumen). El propio `backend/scripts/channex_claim_test_hotel.py` lo llama *adquisición de
turno*. Conseguido el turno, abre una ventana de dos o tres horas.

El problema de que esas dos frases sigan en presente no es de estilo: **invitan a planificar sobre
un recurso que no está disponible a demanda**. Ya ha pasado — al plantear cómo probar la
aplicación completa antes de producción, Channex se descartó por esto mismo después de contarse
como opción disponible.

Esta entrada la abrió `pms-beds24-adapter` el 2026-08-05 a partir de la experiencia operativa con
el turno. Nota larga: `sdd/roadmap/channex-validation-limits.md`.

## What changes

Las dos afirmaciones pasan a distinguir **lo que es permanente** de **lo que fue un tiro único**, y
se registra el coste operativo del turno como entrada de diseño para quien vuelva a planificar
validación contra un PMS real. Además, la spec documenta un fixture capturado que hoy omite. **Sin
código de producto**: es corrección de specs y de steering.

**No se retira nada** (decisión de Jose al abrir este change): Channex sigue siendo la única vía al
entorno de test de Booking.com entre los once proveedores evaluados en
[ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md), y su decisión 2 sigue
prescribiendo abrirlo. La corrección es de tiempo verbal y de expectativa, no de estrategia.

## Requirements

### R1 — Lo permanente y lo que fue un tiro único quedan separados

**Como** quien planifica una validación contra un PMS real, **quiero** que la spec distinga el
valor de regresión del valor de validación en vivo, **para que** no cuente con un recurso que
depende de un turno.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar en `sdd/specs/pms-channex-staging.md` que el **valor de regresión es
   permanente y no depende del hotel de test**: los payloads reales están capturados y commiteados
   en `backend/tests/integrations/fixtures/channex/`, y la propia spec ya exige alimentar con ellos
   los tests del mapeo **sin ninguna llamada de red**, de modo que la suite de CI no depende de la
   cuenta de staging ni volverá a depender.
2. THE SYSTEM SHALL declarar que **la validación end-to-end contra una OTA viva fue un tiro
   único**, ya amortizado, y NEVER SHALL describirla en presente como capacidad disponible.
3. THE SYSTEM SHALL conservar el registro de que ese tiro único produjo hallazgos con carácter
   normativo, nombrando al menos el que originó la **regla 13** de `steering/security.md`: que
   **toda** reserva de OTA llega con un objeto `guarantee` con `card_number`, `cvv` y
   `expiration_date`.
4. THE SYSTEM NEVER SHALL retirar la capacidad ni borrar el `ChannexAdapter` de la spec: sigue
   siendo la única vía documentada al entorno de test de Booking.com.

### R2 — `product.md` deja de afirmar que se usa hoy

**Como** lector del steering de producto, **quiero** que el matiz sobre Channex describa el estado
real, **para que** «ya se usa hoy» no se lea como una capacidad con la que contar.

Criterios de aceptación:

1. THE SYSTEM SHALL corregir la línea 11 de `sdd/steering/product.md` para que NEVER SHALL afirmar
   que el entorno de staging *«ya se usa hoy»* como banco de pruebas.
2. THE SYSTEM SHALL conservar en esa misma línea los dos hechos que sí siguen siendo ciertos y que
   justifican su existencia: que Channex es el único proveedor evaluado con acceso al entorno de
   test de Booking.com, y que existe un `ChannexAdapter` operativo de dev/staging y no de
   producción.
3. THE SYSTEM SHALL mantener explícito que esto **no reabre** la decisión de ADR 0006: Beds24
   sigue siendo el proveedor del MVP y Channex sigue siendo de fase SaaS.

### R3 — El coste operativo del turno queda registrado como entrada de diseño

**Como** quien vuelva a planificar validación contra un PMS real, **quiero** el coste del turno
escrito con sus números, **para que** la decisión se tome con datos y no se repita la
investigación.

Criterios de aceptación:

1. THE SYSTEM SHALL registrar que los hoteles de test de Booking.com son un **pool con reserva por
   franjas, no recursos a demanda**, y que la comprobación de unicidad es **global entre cuentas**,
   de modo que un turno puede perderse ante otro integrador en el intervalo.
2. THE SYSTEM SHALL registrar que **no existe cola ni reserva de turno**, que la ventana útil es de
   **dos o tres horas**, y que **algunos IDs no aceptan reservas en absoluto** con el aviso visible
   solo en la ficha por hotel y no en la lista resumen.
3. THE SYSTEM SHALL situar ese registro donde lo encuentre quien planifica —la spec y/o
   `docs/channex-staging.md`— y NEVER SHALL duplicar las cifras en más de un sitio: uno es la casa
   y el resto cita.

### R4 — El fixture de mensajes existe y la spec lo omite

**Como** quien busca payloads reales de mensajería de OTA, **quiero** que la spec declare lo que
hay capturado, **para que** no se dé por inexistente lo que ya está en el repositorio.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar en `sdd/specs/pms-channex-staging.md` la existencia de
   `backend/tests/integrations/fixtures/channex/message_threads.json`, hoy no mencionado en ninguna
   parte de la spec salvo por el glob de Key files.
2. THE SYSTEM SHALL describir qué es: un hilo de mensajes **real de Booking.com** capturado el
   2026-08-03, con `provider`, `sender`, `ota_message_thread_id`, `message_count`, `is_closed`,
   `attachments` y relaciones a property, channel y booking.
3. THE SYSTEM SHALL declarar con la misma claridad **qué NO permite validar**: el contenido del
   mensaje y el título llegan `***scrubbed***` por la política fail-closed de anonimización —
   correctamente—, así que sirve para el **sobre y el mapeo**, nunca para el tratamiento del
   contenido. Y es forma de **Channex**, no de Beds24: `beds24-messaging-adapter` no hereda de aquí
   la forma de sus payloads.

## Out of scope

- **Que hoy no haya ninguna superficie de validación en vivo disponible.** La nota de esta entrada
  cierra afirmando que *«la única superficie de validación en vivo disponible a demanda es Beds24
  sobre los anuncios reales»*, y eso dejó de ser cierto el 2026-08-17, cuando venció la cuenta de
  medición de Beds24. Jose acotó este change a la corrección sobre Channex, así que ese hecho **no
  se toca aquí**: ya está registrado en `docs/beds24-spike.md` §Alta de la cuenta y en el
  `deferred-until:` de las dos entradas `beds24-*` del roadmap.
- **Retirar la capacidad de Channex**, evaluada y descartada al abrir este change (ver *What
  changes*).
- **Volver a validar contra Channex**, que es precisamente lo que depende del turno.
- **Cualquier código de producto**, incluido el `ChannexAdapter`, sus tests y sus fixtures. Este
  change no toca `backend/`.
- **La regla 13 de `steering/security.md`**, que se cita como consecuencia del tiro único pero no se
  modifica: su casa es el steering de seguridad.

## Affected specs

- `sdd/specs/pms-channex-staging.md` — §Purpose (R1) y la sección de fixtures (R4).
- `sdd/steering/product.md` — **no es una spec, pero se modifica**: es una de las dos afirmaciones
  a corregir (R2). Se registra aquí porque el archivado tiene que verlo.
- `docs/channex-staging.md` — posible casa del registro de coste operativo (R3), si el design
  decide que va ahí en vez de en la spec. Ya contiene las mediciones crudas del turno. El design
  eligió que sí (D1), y corrige además su frase de apertura (D3).
- `docs/README.md` — **añadido durante `/sdd:run`**: su línea 8 repetía la misma afirmación en
  presente, y es el índice desde el que se llega al runbook. Cuarta aparición, no prevista en la
  lista de arriba; la encontró el grep de la tarea 4.1. Se registra aquí porque el archivado tiene
  que verlo.
