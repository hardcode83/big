# Blocked — channex-staging-adapter

Estado al cierre del primer `/sdd:run` (2026-08-03): secciones 2 (parcial) y 3 completas y
verificadas; el resto bloqueado por dos causas independientes — **no hay cuenta de Channex
staging** y **Docker no arranca en esta máquina**.

---

## 1. Cuenta de Channex staging inexistente

- **Fase**: run
- **Tipo**: `decision` — requiere una acción humana que el agente no puede hacer
- **RESUELTO en su mayor parte (2026-08-03)**: cuenta de staging dada de alta por el
  operador, `CHANNEX_API_KEY` en `.env`, y el sandbox provisionado **por API** con
  `scripts/channex_bootstrap.py` (property `7963f1e3-…`, room type `6907ddd0-…`, rate plan
  `81c384be-…`, apps `booking_crs` y `channex_messages`, dos reservas de test). Fixtures
  reales capturados y secciones 3, 4 y 5 completas. Cero pasos de panel.
- **Corrección de una premisa de ADR 0006, y va a R6 como desviación**: el ADR y la entrada
  del roadmap afirman que Channex **presta** propiedades de test y que el entorno de test de
  Booking.com se consigue pidiéndoselo a su soporte. **No es así**: su documentación publica
  ocho hotel IDs de test ya conectados en staging, self-serve, sin petición ni espera
  (`https://docs.channex.io/guides/test-account-for-booking.com`). El único en **EUR** es
  **`4372137`**; los demás son GBP/USD/JPY y no mapearían contra un rate plan en euros
  (*"Make sure your rate plans are in the same currency or you will not be able to map"*).
- **Lo que sí es un paso de panel irreducible**: el **mapeo de canal no se puede hacer por
  API** — *"Access to the channel API is only for Whitelabel accounts"*. Hay que conectar
  Booking.com con el ID `4372137` en la propiedad de staging y mapear room type + rate plan
  (*"Channel wont be activated unless you map rooms and rates"*), y después crear la reserva
  abriendo `https://secure.booking.com/book.html?hotel_id=4372137&test=1` con la tarjeta de
  test `4111-1111-1111-1111`, CVC `123`, caducidad futura.
- **Aviso**: las propiedades de test son **compartidas** entre integradores de Channex, así
  que pueden aparecer reservas ajenas en la cuenta. Es ruido en los fixtures, no un problema
  — pero verlo sin saberlo asusta.
- **Y son un pool con reserva por franjas horarias, no recursos a demanda** (medido
  2026-08-03 ~12:30 en el diálogo *Create Channel*): los **ocho** hotel IDs aparecían
  simultáneamente como *"In use until August 3rd 2026, HH:MM"* y el intento de conexión
  devolvía *"Incorrect Connection — This Hotel ID is already in use"*. Los de liberación más
  próxima eran `10485037` (USD) a las 13:00 y `4372137` (EUR) a las 13:50. **Consecuencia
  para R5**: la reserva end-to-end real no está disponible cuando uno quiere, hay que
  esperar turno — y no vale coger el que se libere antes, porque la moneda del hotel de test
  tiene que coincidir con la del rate plan (el nuestro es EUR, así que solo sirve
  `4372137`). ADR 0006 presenta esta capacidad como la ventaja decisiva de Channex sobre
  Beds24 y sigue siéndolo, pero con una latencia de agenda que el ADR no contempla.
- **Bloquea todavía**: 2.3 (el fixture de mensaje necesita una conversación real de huésped,
  que una reserva creada por CRS no genera), 6.2, 6.3, y 8.7 (que además necesita un tenant
  sembrado en la base de datos de dev).
- **El riesgo con peor consecuencia del change sigue intacto**: nada de esto toca los
  anuncios reales. `4372137` es un hotel de test de Booking.com, no REDES11 ni PAJARITOS8.
  No conectar la cuenta real de Airbnb (un solo channel manager por cuenta; Channex falla en
  duro si ya hay otro, y desconectar el actual abriría ventana de corte sobre dos anuncios
  que están vendiendo).
- **Comando de reanudación**: `/sdd:run channex-staging-adapter 6`

## 2. Fixtures reales ausentes → sección 4 sin entrada

- **Fase**: run
- **Tipo**: `decision`
- **Qué y por qué**: las tareas 4.1–4.3 dicen "tests contra los fixtures de 2.3", y 2.3
  necesita la cuenta. El orden de `tasks.md` es deliberado —"no se puede mapear un payload
  que no has visto"—, así que hay una decisión que tomar y no la tomo yo:
  **(a)** esperar a los payloads reales, o **(b)** escribir fixtures sintéticos derivados
  de la documentación de Channex, marcados `ASSUMPTION`, y reemplazarlos en 2.3. La opción
  (b) adelanta trabajo real (el mapeo y sus tests son correctos frente al contrato
  documentado) a cambio de que los nombres de campo puedan no coincidir con la realidad,
  que es exactamente lo que este change existe para descubrir.
- **Bloquea**: 4.1, 4.2, 4.3, 4.4, 4.5 y, por dependencia, 5.1–5.4 (el flag `--provider
  channex` tiene que construir un `ChannexAdapter` que aún no existe).
- **Comando de reanudación**: `/sdd:run channex-staging-adapter 4`

## 3. ~~Docker parado~~ → RESUELTO 2026-08-03

El usuario levantó el stack y las seis verificaciones que no dependen de la cuenta pasaron:

- **8.1** `docker compose exec backend uv run pytest` → **2331 passed, 35 skipped**. La
  suite completa en verde con los cambios dentro, incluido `tests/test_config.py`, que era
  el riesgo real de haber añadido cinco campos a `Settings`.
- **8.2** `alembic check` → *No new upgrade operations detected* (este change no añade
  migración, y queda demostrado).
- **8.3** `make openapi` + `git diff --exit-code backend/openapi.json` → sin cambios, como
  debe ser: no se añade ninguna ruta.
- **8.4** `uv sync --frozen` dentro del contenedor → limpio, así que el `uv.lock`
  regenerado en 3.1 es coherente y CI no fallará por él.
- **8.5** La que de verdad importaba: `docker build --target prod` y dentro de esa imagen
  `import httpx` → **0.28.1**, y `ChannexClient` importable. Sin el movimiento de 3.1 esto
  habría pasado la suite y roto el despliegue, porque la etapa `prod` instala con
  `--no-dev`.
- **8.6** `printenv | grep -c CHANNEX` → `0`, así que la corrida de 8.1 fue de verdad con
  la cuenta de staging inalcanzable.

**Sigue pendiente**: 8.7 (comprobación manual end-to-end) y 8.8 (revisar el diff de
fixtures), que dependen del bloqueo 1.

## 4. Últimos hallazgos del panel corregidos sin re-review

- **Fase**: run (panel de la sección 3)
- **Tipo**: `deferred`
- **Qué y por qué**: el panel dio 6 hallazgos en dos rondas y están los 6 corregidos, pero
  los **2 últimos** (seguridad ronda 2: el fail-closed solo cubría hojas de texto, y
  `source` como texto libre en la allowlist) se arreglaron **después** de agotar el
  presupuesto de 2 rondas de fix que marca `/sdd:run`, así que **ningún reviewer ha
  confirmado ese último arreglo**. La verificación que sí existe: 47 tests en verde y una
  comprobación directa contra los payloads exactos que el reviewer usó para demostrar las
  fugas (`national_id`, `tax_id`, `contact_at`, `guest_number` numérico, `source`, clave de
  diccionario con email, float con teléfono) — cero fugas, y los campos que el mapeo de la
  sección 4 necesita intactos byte a byte.
- **Dos residuales de QA declarados no bloqueantes**, ambos ya cubiertos: (a) `meta.limit`
  podía ser un eco del `?limit=` que pedimos, resuelto ignorándolo cuando coincide con lo
  solicitado y paginando hasta página vacía; (b) el orden allowlist/needles, resuelto al
  quitar los sufijos `_id`/`_at`.
- **Comando de reanudación**: `/sdd:review channex-staging-adapter`

---

## Nota fuera del alcance de este change

`sdd/project.md` afirma que «`uv` no está instalado en el host». Es falso hoy:
`which uv` → `/Users/hardcode/.local/bin/uv`, y es lo que permitió verificar la sección 3
sin Docker. Corregirlo ahorra ese descubrimiento en cada run futuro, pero es una edición
de `project.md` ajena a este change — candidata a arreglo aparte.
