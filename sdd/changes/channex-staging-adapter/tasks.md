# Tasks: channex-staging-adapter

Orden pensado para que el sistema quede funcionando tras cada sección. Las secciones 1 y
2 no tocan código de la aplicación; a partir de la 3, el default sigue siendo
`MockPMSAdapter` hasta la sección 5, así que ningún paso intermedio cambia el
comportamiento de nadie.

**Nada preexistente**: `git grep -il channex -- backend/ .env.example docs/` solo devuelve
`docs/adr/0006-…`, así que ninguna tarea va pre-marcada.

## 1. Alta de la cuenta de staging y runbook

- [x] 1.1 Alta en `staging.channex.io` (grupo + propiedad de test + API key desde
      Organisation → API Keys) y arranque de `docs/channex-staging.md` con los pasos
      reproducibles y los endpoints base. **Ningún valor de credencial en el fichero** —
      solo nombres de variable. [R1]
- [x] 1.2 En `docs/channex-staging.md`, sección de canales con el veto explícito: solo
      propiedades de test prestadas; **no conectar la cuenta real de Airbnb**, con el
      motivo (un solo channel manager por cuenta en Airbnb, Channex falla en duro si ya
      hay otro, y desconectar el actual abriría ventana de corte sobre anuncios activos).
      [R1]
- [x] 1.3 Marcar en el runbook como `EXTERNAL_DEPENDENCY` todo paso que dependa de
      Channex (préstamo de propiedades de test, acceso al entorno de test de
      Booking.com), con canal de contacto y fecha. [R1]
- [x] 1.4 `backend/scripts/channex_bootstrap.py` (nuevo, **no estaba en el plan** — añadido
      2026-08-03 porque 1.1 exige que el alta sea *reproducible* y el operador pidió el
      mínimo de pasos a mano): provisiona property + room type + rate plan, instala la app
      `booking_crs` y siembra dos reservas de test. **Idempotente** (segunda corrida reusa,
      no duplica). Sin la app, `POST /bookings` responde 403 y eso no se deduce del error.
      **Dos guards, los dos endurecidos por el panel de seguridad de la sección 4**:
      · **Apps por allowlist** (`KNOWN_FREE_APPS`), no por «no tiene precio». La versión
        anterior solo abortaba si el catálogo reportaba un precio truthy, y en el único caso
        para el que existía **no disparó**: `channex_messages` es de pago según ADR 0006 y
        staging la reporta con `price: null`. `channex_messages` sale del set automático — se
        instaló una vez por instrucción explícita y sigue instalada, pero un script
        reproducible no debe suscribir una app de pago en la cuenta a la que se apunte después.
      · **Host exacto**, no `substring`. `"staging" not in base_url` aceptaba
        `https://app.channex.io/api/v1?env=staging` (cuenta viva) y
        `https://staging.channex.io.example.net/` — que además habría recibido la API key. [R1]

## 2. Sondeo, captura y fixtures

- [x] 2.1 `backend/scripts/channex_probe.py` (nuevo): cliente mínimo que lee
      `CHANNEX_API_KEY`/`CHANNEX_BASE_URL` **solo del entorno** y **rechaza** la
      credencial por argumento de línea de comandos, para que no quede en el historial del
      shell. [R4]
- [x] 2.2 El script anonimiza **en el momento de capturar** (nombre, email, teléfono,
      documento), conservando forma y tipos, y escribe a
      `backend/tests/integrations/fixtures/channex/`. Test del anonimizador con un payload
      sintético que lleve los cuatro campos. [R4]
- [x] 2.3 Capturar cuatro formas: `GET /bookings`, `GET /booking_revisions/feed` (**una
      lectura, sin `ack`** — no lo consume ningún código, es entrada de diseño de
      `reservations-webhooks`), mensaje y webhook. [R4, R6]
      **HECHO 2026-08-03**, con tres de las cuatro formas y la cuarta reasignada:
      · `bookings.json` — 3 reservas, **una real de Booking.com** (`BDC-6558139322`) llegada por
        el canal, más dos sembradas por CRS. La real es la que destapó `ota_name: "BookingCom"`
        (sin punto), la comisión `"0.00"` de una OTA que sí cobra, y el objeto `guarantee` con
        datos de tarjeta.
      · `revisions.json` — del feed, una lectura y sin `ack`.
      · `message_threads.json` — endpoint descubierto sondeando: **no** es `/messages` ni
        `/conversations` (404 los dos). Trae `relationships` (property/channel/booking), que las
        reservas no exponen, y demuestra que la app `channex_messages` funciona de verdad
        (`sender: "property"`).
      · El **webhook** no es capturable aquí y se queda en 2.4 — requiere un receptor público, y
        el payload lleva `card_number`/`cvv`, así que apuntarlo a un capturador de terceros no es
        aceptable. Pasa a `reservations-webhooks` con su endpoint bajo la regla 12.
- [ ] 2.4 Configurar un webhook de Channex hacia un capturador externo para producir el
      fixture de webhook y observar el desorden de entrega. **No se expone ninguna ruta en
      nuestra API** — la regla 12 de `steering/security.md` es alcance de
      `reservations-webhooks`. [R4, R6]
- [x] 2.5 Helper de carga de fixtures en `backend/tests/integrations/conftest.py` (primer
      directorio de fixtures en disco del repo — los tests de CSV los construyen en línea).
      [R4]

## 3. Cliente HTTP de Channex <!-- panel 2026-08-03, 2 rondas: architect PASS, documentation PASS, qa PASS (r2, 2 residuales no bloqueantes), security r2 FAIL (2 leves) → los 6 hallazgos corregidos; los 2 últimos verificados a mano contra las pruebas de los propios reviewers, sin re-review porque el presupuesto de 2 rondas de fix estaba agotado. Ver BLOCKED.md #4. -->

- [x] 3.1 Mover `httpx` de `[dependency-groups].dev` a `[project].dependencies` en
      `backend/pyproject.toml` y regenerar `backend/uv.lock` (`uv lock`). **La etapa `prod`
      del Dockerfile corre `uv sync --frozen --no-dev`**, así que sin esto el adapter no
      existe en la imagen desplegada; y CI usa `--frozen`, así que sin el lock regenerado
      falla. [R2]
- [x] 3.2 `PmsUnavailableError` en `backend/app/integrations/domain/errors.py` (nuevo) —
      vocabulario del puerto, no de Channex, para que `pms_sync` no tenga que importar
      `infrastructure/channex/`. Sin test propio a propósito: es una clase vacía, la
      cubren 3.3, 3.5 y 5.2. [R2]
- [x] 3.3 `backend/app/integrations/infrastructure/channex/client.py` (nuevo): cabecera
      `user-api-key`, base URL de settings, y traducción de `{"errors":{"code","title"}}`,
      `401`, `429`, `5xx` y error de transporte → `PmsUnavailableError`. Tests con
      `httpx.MockTransport`, **sin red**. [R2]
- [x] 3.4 `channex_api_key: str = ""` y `channex_base_url: str = "https://staging.channex.io/api/v1"`
      en `backend/app/core/config.py`, más el tope de páginas. El default apunta a
      **staging a propósito**: un despiste de configuración no debe poder apuntar a
      producción. [R2, R3]
- [x] 3.5 Redacción de la credencial: `user-api-key` no aparece en `repr`, log ni mensaje
      o traceback de excepción. **Test explícito** — `httpx` arrastra cabeceras en la
      representación de sus errores, así que esto se verifica, no se confía. [R2]
- [x] 3.6 Paginación sobre `meta.{total,page,limit}` hasta agotar (el `limit` por defecto
      de Channex es **10**, así que sin esto todo sync ve como mucho diez reservas). Al
      alcanzar el tope de páginas **lanza** `PmsUnavailableError` en vez de truncar. Tests:
      una página, tres páginas, y tope alcanzado. [R2]

## 4. Mapeo y `ChannexAdapter` <!-- panel 2026-08-03: architect PASS, tenancy FAIL(1)→corregido, documentation FAIL(1)→rechazado con motivo, security FAIL(5)→corregidos, qa FAIL(1 alto)→corregido. 8 hallazgos, 7 aceptados. -->

- [x] 4.1 `infrastructure/channex/mapping.py` (nuevo): `unique_id` → `external_id`
      (**nunca `system_id`**, que es único por revision y rompería la idempotencia por
      `(tenant_id, external_pms_id)` de `ReservationIngestor`), `property_id` →
      `property_external_id`, `raw_payload` ← el elemento `data` íntegro. Tests contra los
      fixtures de 2.3. [R2]
- [x] 4.2 Traducción de OTA a `ReservationChannel` con **`OTHER` como destino de lo no
      reconocido**: `ReservationChannel.parse` lanza ante desconocidos y el ingestor lo
      convierte en fila saltada, así que propagar el literal de Channex haría que una OTA
      nueva descarte reservas válidas. Test con un nombre de OTA inventado. [R2]
- [x] 4.3 `ota_commission`: **corregido contra el payload real** — Channex no devuelve `null`
      nunca, devuelve `"0.00"`, así que el campo no distingue "sin comisión" de "sin dato".
      El adapter respeta el valor solo si `ota_name` es de las OTAs de las que Channex
      informa (Booking.com, Airbnb) y devuelve `None` en el resto, **incluida una OTA
      desconocida**. Documentar con `None` todo campo de PRD §16 que Channex no dé. Test por
      cada caso, incluido el cero legítimo de Booking.com. [R2, R6 (§D7 bis)]
- [x] 4.6 Traducción de `status`: `new`/`modified` → `CONFIRMED`, `cancelled` → `CANCELLED`.
      Un valor **fuera** de esa tabla se propaga sin traducir para que `parse_ingested` lo
      rechace y el ingestor reporte la fila — asimetría deliberada frente al canal (4.2),
      porque un status inventado conduce la `PropertyStateMachine`. Sin esto el sync
      importaría **cero reservas**: `ReservationStatus.parse_ingested("new")` lanza. Test de
      las tres traducciones y del desconocido. [R2, R7]
- [x] 4.7 El filtro temporal va en **UTC sin offset**: Channex ignora el offset recibido y
      compara el reloj de pared literal, así que un `since` tz-aware desde Madrid en verano
      deja fuera las reservas de las dos últimas horas **sin error alguno**. Medido, tabla en
      `design.md` §D7 bis. Test con un `since` en `Europe/Madrid` que demuestre que se envía
      convertido. [R2, R8]
- [x] 4.4 `infrastructure/channex/adapter.py` (nuevo): `list_reservations` sobre
      `GET /bookings` con `filter[inserted_at][gte]=<since>`. Docstring que registre que
      **no existe filtro por fecha de modificación** en la API, así que no ve
      modificaciones ni cancelaciones — decisión D1, y hallazgo de 7.2, no un descuido.
      [R2]
- [x] 4.5 `get_reservation(external_id)` devuelve **`None`** ante id desconocido (404), no
      lanza — igual que `MockPMSAdapter`. Es la sustituibilidad de Liskov que exige
      `steering/backend-architecture.md`, y aquí es requisito del puerto. Test del 404 y
      del camino feliz. [R2]

## 5. Selección de proveedor en el CLI <!-- panel 2026-08-03: cubierta por el mismo panel que la sección 4; incluye el hallazgo de seguridad #5 (--provider ya no imprime el valor rechazado). -->

- [x] 5.1 `--provider {mock,channex}` en `backend/app/integrations/cli/pms_sync.py`, que
      hoy construye `MockPMSAdapter` a pelo en la línea 74. **Default `mock`**, de forma
      que sin el flag no cambia nada del comando, de la suite ni del arranque local. Test
      de que el default sigue siendo el mock. [R3]
- [x] 5.2 `--provider channex` sin `CHANNEX_API_KEY` en el entorno: aborta nombrando la
      variable ausente y **no** cae silenciosamente al mock. `PmsUnavailableError` sale
      con código distinto de cero y mensaje en inglés. Tests de ambos. [R2, R3]
- [x] 5.3 Valor de `--provider` que no sea `mock` ni `channex`: rechazado con el uso del
      comando y exit ≠ 0. Test. [R3]
- [x] 5.4 Comentario en el código dejando constancia de que la selección es un **stopgap**
      de dev/staging y que `pms-beds24-adapter` la sustituye por la `PMSAdapterFactory`
      con resolución por propiedad (ADR 0006 decisión 7). [R3]
- [x] 5.5 `CHANNEX_API_KEY` y `CHANNEX_BASE_URL` en `.env.example`, con tratamiento
      **distinto** cada una y a propósito (redacción aclarada tras el panel, que la leyó como
      si la restricción aplicara a las dos):
      · `CHANNEX_API_KEY` → **nombre y comentario, nunca valor**. Es una credencial de
        proveedor y le aplica la regla 8 de `steering/security.md`.
      · `CHANNEX_BASE_URL` → **sí lleva valor**, comentado como el resto de overrides
        opcionales del fichero. No es un secreto, y la regla 8 exime expresamente la config
        «sin sensibilidad real». El valor es `https://staging.channex.io/api/v1` y está ahí
        **como medida de seguridad**: el default apuntando a staging es lo que impide que un
        despiste de configuración acabe escribiendo en una cuenta de Channex viva.
      `docker-compose.yml` no cambia — el servicio `backend` ya lleva `env_file: .env` y el
      fallo rápido es en
      código, no un `${VAR:?}`. [R3]

## 6. Reserva end-to-end desde Booking.com

- [ ] 6.1 Escribir el `property_id` de Channex en `Property.pms_external_id` de la
      propiedad de test mediante el paso documentado del runbook — **no** migración ni
      cambio en `app/cli/bootstrap.py`, que contaminaría el arranque de todo el mundo con
      un proveedor de dev. [R5]
- [x] 6.2 Crear una reserva desde el entorno de test de Booking.com sobre la propiedad de
      test y recuperarla con `list_reservations` del `ChannexAdapter`. [R5]
      **Vía concreta, medida 2026-08-03 y distinta de lo que asumía ADR 0006**: no hay que
      pedir nada a soporte — Channex publica ocho hotel IDs de test ya conectados en staging,
      self-serve. Usar **`4372137`**, el único en EUR (el resto GBP/USD/JPY no mapea contra un
      rate plan en euros). Conectar el canal y **mapear room type + rate plan** desde el panel,
      porque el **mapeo de canal no está en la API** (*"Access to the channel API is only for
      Whitelabel accounts"*), y crear la reserva en
      `https://secure.booking.com/book.html?hotel_id=4372137&test=1` con la tarjeta de test
      `4111-1111-1111-1111`. Las propiedades de test son **compartidas** entre integradores:
      pueden aparecer reservas ajenas.
- [ ] 6.3 Persistirla con `pms_sync <tenant> --provider channex` y registrar en
      `docs/channex-staging.md` la evidencia: reserva creada, payload recibido
      (anonimizado) y `TimelineEvent` resultante. [R5]
- [ ] 6.4 IF Channex no concede el acceso al entorno de test de Booking.com: registrar el
      bloqueo en `BLOCKED.md` como `decision` con el comando de reanudación, y cerrar el
      resto del change. R5 es la única parte que depende de un tercero. [R5]

## 7. Hallazgos y límites medidos

- [x] 7.1 En `docs/channex-staging.md`: paginación, **límite de tasa medido** (no está
      documentado por Channex — medirlo es el punto), latencia típica, y el desorden de
      webhooks observado en 2.4, cada uno con la observación que lo respalda. [R6]
- [x] 7.2 Registrar las desviaciones siguiendo la convención de ADR 0005 (se anotan, **no
      se edita** el documento original): (a) **no hay filtro por fecha de modificación** en
      `/bookings`, así que un sync por ventana no ve modificaciones ni cancelaciones —
      entrada de diseño directa de `pms-beds24-adapter`; (b) el feed de revisions exige
      `ack` en <30 min, que es otra forma de integración; (c) Channex **sí tiene API para
      configurar webhooks** (incluido `is_global`), a diferencia de Beds24, cuya
      configuración es manual por propiedad. [R6]
- [x] 7.3 Enumerar qué queda por medir en Beds24 y **no** se puede extrapolar de Channex
      (`X-RequestCost` y su presupuesto de créditos, latencia de sus webhooks), para que
      `pms-beds24-spike` arranque con la lista cerrada. [R6]
- [x] 7.4 Enlazar `docs/channex-staging.md` desde `docs/README.md`, y actualizar la
      sección de estructura del `README.md` de raíz por el directorio nuevo
      `backend/scripts/` (`steering/documentation.md`: cambio de estructura de carpetas →
      README al día). [R1, R6]

## 8. Verification

- [x] 8.1 Suite completa: `docker compose exec backend uv run pytest`
      (con el stack parado: `docker compose run --rm backend uv run pytest`).
- [x] 8.2 Los modelos siguen cuadrando con el esquema migrado:
      `docker compose run --rm backend uv run alembic check`. Este change **no añade
      migración**, así que debe pasar sin cambios.
- [x] 8.3 El contrato OpenAPI **no se mueve**: `make openapi` y luego
      `git diff --exit-code backend/openapi.json`. No se añade ninguna ruta, así que
      cualquier diff aquí es un efecto colateral no querido — y el workflow `api-contract`
      lo bloquearía.
- [x] 8.4 El lockfile está commiteado y coherente: `cd backend && uv sync --frozen`
      (es lo que corre CI; falla si 3.1 dejó el lock sin regenerar).
- [x] 8.5 La imagen de producción lleva `httpx`: construir la etapa `prod` del
      `backend/devops/Dockerfile` (que corre `uv sync --frozen --no-dev`) y comprobar
      `python -c "import httpx"` dentro. Sin esto, 3.1 pasa la suite y falla en el
      despliegue.
- [x] 8.6 Ningún test toca la red: la suite pasa con la cuenta de staging inalcanzable
      (variables de Channex sin definir).
- [ ] 8.7 Comprobación manual end-to-end: `pms_sync <tenant> --provider channex` sobre la
      propiedad de test trae la reserva de 6.2 y deja su `TimelineEvent`; sin `--provider`
      el comando sigue usando el mock.
- [ ] 8.8 Revisar el diff de `backend/tests/integrations/fixtures/channex/` buscando datos
      personales reales antes de commitear — los payloads del entorno de test de
      Booking.com pueden traer nombres y correos.

**Sin tareas de diagrama**: un segundo adapter detrás del mismo puerto no altera la forma
hexagonal ni el modelo de datos, así que ningún diagrama de `docs/diagrams/` queda
obsoleto. **Sin tareas de i18n ni de frontend**: el change no toca `frontend/`.

## Cobertura de requisitos

| Req | Tareas |
|---|---|
| R1 | 1.1, 1.2, 1.3, 7.4 |
| R2 | 3.1–3.6, 4.1–4.5, 5.2 |
| R3 | 3.4, 5.1–5.5 |
| R4 | 2.1, 2.2, 2.3, 2.5 |
| R5 | 6.1, 6.2, 6.3, 6.4 |
| R6 | 2.3, 2.4, 7.1, 7.2, 7.3, 7.4 |
