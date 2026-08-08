# BLOCKED — reservations-webhooks

Tres entradas. Las dos primeras son **decisiones que necesitan a Jose** y estaban previstas: el diseño
las tomó de forma provisional y marcada para no detener el flujo, no para darlas por buenas. La tercera
es el estado de la implementación, para que se pueda reanudar sin reconstruir nada de la conversación.

---

## 1. La forma de la redacción de `special_requests` (regla 13)

- **Fase**: design (decidido provisionalmente) · afecta a las tareas 3.1 y 3.2
- **Tipo**: `decision` — necesita un humano
- **Qué y por qué**

  `pms-beds24-adapter` acotó la regla 13 a `raw_payload` y dejó `special_requests` fuera, con una
  condición literal en su tarea P.8 y su D9: *"se vuelve exigible en cuanto exista una escritura no
  autenticada desde internet sobre esa misma columna, que es lo que traen `reservations-webhooks` y
  `beds24-messaging-adapter`"*. **Este change es esa escritura**, así que la condición se ha cumplido y
  la frontera vuelve a estar abierta. Aquella decisión la tomó Jose el 2026-08-06; esta le corresponde
  igual.

  El campo lo llenan `comments` (Beds24) y `notes` (Channex), viaja a `reservations.special_requests` y
  sale en la respuesta de la API. Lo lee el personal de limpieza.

  **Lo decidido provisionalmente (D8)**: redactar rachas de 13-19 dígitos —ignorando espacios y
  guiones— **sólo** en texto de origen externo (webhook y sync de PMS), dejando intacto lo que una
  persona escribe por la API. Sin comprobación de Luhn.

  **El compromiso a ratificar**: sin Luhn hay falsos positivos reales. Una referencia de reserva larga
  o un número de teléfono internacional pegado pierden sus dígitos en una nota operativa. A cambio, un
  PAN no queda persistido en claro en una columna que la API devuelve.

  **Alternativas, con el motivo por el que no se eligieron** (detalle en D8):
  - Luhn completo — D9 de `pms-beds24-adapter` ya lo rechazó por falsos positivos reales sobre un campo
    operativo, y no ha aparecido nada nuevo que lo justifique.
  - Descartar el campo entero cuando la fuente es externa — tira información real ("llegamos a las
    23:00", "el código del portal es…") por un riesgo que la redacción acota.
  - Volver a diferirlo — P.8 dice "bloqueante", no "diferible otra vez".

- **Cómo se resuelve**: elegir una de las cuatro. Si es la provisional, basta decirlo y se quita el
  `ASSUMPTION` de D8, de `docs/reservations-webhooks.md` y de esta entrada.
- **Comando para reanudar**: `/sdd:run reservations-webhooks 3`

---

## 2. Añadir `attempts` y `next_attempt_at` a `webhook_events` (desviación de PRD §7.26)

- **Fase**: design (decidido provisionalmente) · **ya implementado** en la tarea 1.2
- **Tipo**: `decision` — necesita un humano
- **Qué y por qué**

  PRD §7.26 declara la forma de `WebhookEvent` y es documento **cerrado**. PRD §16 pide a la vez "3
  reintentos con backoff exponencial" y no le da a la entidad ningún sitio donde recordar ni el contador
  ni el instante. Las dos cosas no se pueden cumplir tal como están escritas.

  **Lo decidido provisionalmente (D9)**: dos columnas nuevas, `attempts SMALLINT NOT NULL DEFAULT 0` y
  `next_attempt_at TIMESTAMPTZ NULL`. Aditivas, de contabilidad puramente interna, sin cambiar la
  semántica de ninguna columna que §7.26 sí declara. Es la **quinta desviación del PRD** de este
  proyecto, y las cuatro anteriores están registradas en ADR.

  **Ya está en el árbol** (migración `a4d17e83b6c1`), porque el resto de la sección 4 se apoya en ellas.
  Revertirlo es una migración menos y reescribir la tarea 4.3.

  **Alternativa, con su coste** (detalle en D9): una subtarea Celery por evento con `autoretry_for` +
  `retry_backoff`, que no necesita esquema. El estado del reintento vive entonces en el broker, así que
  un reinicio del worker lo pierde y —peor— el job por cadencia no puede distinguir "en vuelo" de
  "pendiente", con lo que reprocesa el mismo evento. También se descartaron un contador en Redis (caduca,
  y el evento se reintenta para siempre) y una tabla aparte (un join en la consulta caliente a cambio de
  nada).

- **Cómo se resuelve**: ratificar la desviación —y entonces decidir si merece entrada propia en ADR, como
  las cuatro anteriores— o pedir la alternativa Celery.
- **Comando para reanudar**: `/sdd:run reservations-webhooks 4`

---

## 3. La implementación está a medias (sección 1 de 6)

- **Fase**: run
- **Tipo**: `deferred` — el flujo puede reanudarlo sin decisión humana
- **Qué y por qué**

  `tasks.md` es la verdad de lo hecho y lo pendiente. Al cerrar esta sesión:

  - **Hecho y verificado, con commit propio cada tarea**: 1.1 (entidad `WebhookEndpoint`, puerto y las
    tres primitivas de autenticación; 20 tests), 1.2 (tabla `webhook_endpoints` + las dos columnas de la
    entrada 2; `alembic upgrade`, `alembic check` sin deriva y `alembic downgrade base`, los tres
    comprobados), 1.3 (repositorio + test de aislamiento propio; 12 tests) y 1.4 (vocabulario de
    auditoría + denylist de la regla 11 para los dos secretos; 10 tests).
  - **Pendiente**: 1.5, 1.6, 1.7 y las secciones 2 a 6 completas.
  - **El panel de la sección 1 NO se ha lanzado**, porque la sección no está cerrada. Cuando se cierre,
    el panel obligatorio son `sdd-architect`, `sdd-security`, `sdd-qa` más los cuatro reviewers de
    proyecto (`sdd-review-{tenancy,i18n,cicd,documentation}`), todos en **un solo mensaje**.
  - Suite en verde en lo tocado: 1395 en `tests/integrations` + tenancy + layering, 119 en `tests/audit`.
    La suite completa (~6m15s) no se ha corrido todavía; es la tarea 6.1.

  **Un hallazgo que la sección 1 destapó y que la 4 tendrá que respetar**: no hay `WEBHOOK_ENDPOINT_READ`
  en el vocabulario de auditoría, a propósito y con test que lo fija. El "read" equivalente ocurre en
  **cada webhook entrante** —anónimo, desde internet, a la cadencia del proveedor—, así que auditarlo
  dejaría que un tercero escriba filas en `audit_logs` a voluntad y ahogaría el índice que la regla 9
  existe para mantener respondible. Lo que se audita es el acto humano de crear o rotar.

  Una corrección de diseño hecha sobre la marcha y ya commiteada, que reduce trabajo: **D5**. El tope de
  tamaño de cuerpo no hay que construirlo — `MaxBodySizeMiddleware`
  (`app/core/http_limits.py:82`, change `api-ingress-routing` D11) ya cubre `/api/v1/` entero, **antes
  del enrutado** y por tanto antes de la autenticación, y ya trata el `Content-Length` ausente, negativo
  y no numérico. La tarea 2.2 pasó de "construir el mecanismo" a "un test que lo demuestra sobre la ruta
  nueva", y `WEBHOOK_MAX_BODY_BYTES` desapareció del diseño.

  Nada queda sin commitear: cada tarea verificada tiene su commit en `sdd/reservations-webhooks`.

- **Dónde vive el trabajo**: worktree
  `/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+reservations-webhooks`, rama
  `sdd/reservations-webhooks`, ya publicada en `origin`. Su stack de Docker está levantado; `make down`
  antes de borrar el worktree.
- **Comando para reanudar**: `/sdd:run reservations-webhooks` (sigue en 1.3; el panel se dispara al
  cerrar cada sección)
