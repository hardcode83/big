# 0007 — Contabilidad de reintentos en `webhook_events`

## Estado

Aceptado — 2026-08-08. Decidido por Jose durante el change `reservations-webhooks` (design D9). Es la **quinta desviación del PRD** que este proyecto registra en ADR, después de [0004](0004-backend-layering-pattern.md), [0005](0005-global-email-uniqueness.md) y las dos que introduce [0006](0006-pms-channel-manager-provider.md).

**Sobre no editar el PRD**: igual que en [ADR 0005](0005-global-email-uniqueness.md) y [ADR 0006](0006-pms-channel-manager-provider.md), el PRD es el documento funcional de origen y su autoría es de Marta. §7.26 no se edita; la desviación se registra aquí y se propagará a `sdd/specs/domain-foundation-financial.md` cuando `reservations-webhooks` se archive.

## Contexto

PRD §7.26 declara la forma de la entidad `WebhookEvent`: `provider`, `event_type`, `payload`, `processed`, `processed_at`, `error`, `received_at`, y un `tenant_id` nullable.

PRD §16 pide, para el procesamiento de esos eventos, **«3 reintentos con backoff exponencial»**.

**Las dos cosas no se pueden cumplir a la vez tal como están escritas.** Un reintento con backoff necesita dos datos que sobrevivan al proceso que los produce: cuántos intentos van, y a partir de cuándo tiene sentido el siguiente. La forma de §7.26 no da sitio para ninguno de los dos. `processed=FALSE` distingue «pendiente» de «hecho», y nada más: no distingue «pendiente porque acaba de llegar» de «pendiente porque ha fallado dos veces y el tercer intento toca dentro de cuatro minutos».

El problema no es teórico ni aplazable: `process_webhook_events` es un job por cadencia, así que sin esos dos datos cada tick reprocesa todo lo que esté en `processed=FALSE`, incluido lo que acaba de fallar, para siempre y sin espaciado. Eso convierte un evento envenenado en un bucle contra la API del proveedor —la misma cuota que la regla 12(d) de `sdd/steering/security.md` existe para proteger.

## Decisión

Dos columnas nuevas en `webhook_events`, por migración:

| Columna | Tipo | Nota |
|---|---|---|
| `attempts` | `SMALLINT NOT NULL DEFAULT 0` | Cuántas veces se ha intentado procesar |
| `next_attempt_at` | `TIMESTAMPTZ NULL` | A partir de cuándo vuelve a ser elegible |

El job selecciona `processed = FALSE AND attempts < 3 AND (next_attempt_at IS NULL OR next_attempt_at <= now)`; al fallar incrementa `attempts` y fija `next_attempt_at = now + backoff(attempts)`. Eso son los «3 reintentos con backoff exponencial» de §16, persistidos.

**Por qué es una desviación aceptable y no un cambio de contrato**: las dos columnas son **aditivas y de contabilidad puramente interna**. No cambian la semántica de ninguna columna que §7.26 sí declara, no alteran lo que significa `processed` ni `error`, y ningún consumidor de la entidad las necesita para interpretarla. Son el «cómo» de una obligación que el propio PRD impone en otra sección.

## Alternativas descartadas

**Una subtarea Celery por evento con `autoretry_for` + `retry_backoff`.** Es la única que no toca el esquema, y por eso se consideró en serio. Se descarta porque **el estado del reintento vive entonces en el broker**: un reinicio del worker lo pierde, y —peor— el job por cadencia no puede distinguir «en vuelo» de «pendiente», así que reprocesa el mismo evento mientras su reintento sigue programado. Cambia un problema de esquema por uno de duplicación silenciosa.

**Contar los intentos en Redis.** El contador caduca, y cuando caduca el evento vuelve a intentarse indefinidamente: es el bucle que esto viene a cerrar, con un retardo.

**Una tabla `webhook_event_attempts`.** Una fila por evento con dos enteros no gana nada frente a dos columnas, y añade un join a la consulta caliente de la cola.

## Consecuencias

- La migración (`a4d17e83b6c1`) es aditiva y con defaults, así que no rompe filas existentes. En el momento de aplicarla la tabla está vacía en todos los entornos, porque hasta este change nadie escribía en ella.
- `sdd/specs/domain-foundation-financial.md` documenta la forma de §7.26 y hay que actualizarla al archivar `reservations-webhooks`, declarando además a ese change como escritor vivo de `payload` y `error`.
- El tope de 3 intentos y el backoff quedan en el código del job, no en el esquema: las columnas registran hechos, no política.
- Si algún día se quisiera revertir, es una migración menos y reescribir la tarea 4.3 del change; nada fuera del módulo `integrations` depende de estas columnas.
