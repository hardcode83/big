# Blocked — channex-staging-adapter

Una sola entrada viva. Las cuatro anteriores —cuenta de Channex inexistente, fixtures ausentes,
Docker parado, y hallazgos de panel corregidos sin re-review— están resueltas y se han **borrado**
en vez de anotarse: la regla 5 del flujo SDD dice que resolver una entrada la elimina, y un
`BLOCKED.md` lleno de bloqueos superados es indistinguible de uno lleno de bloqueos reales.

Lo que aprendieron está en `docs/channex-staging.md`, que es donde tiene valor duradero.

---

## 1. Fixture de webhook (tarea 2.4) — reasignada, no pendiente aquí

- **Fase**: run
- **Tipo**: `deferred`
- **Qué y por qué**: capturar el cuerpo de un webhook de Channex exige un **receptor público**, y
  este change no expone ninguna ruta entrante a propósito: hacerlo obliga a cumplir la **regla 12**
  de `sdd/steering/security.md` entera (autenticación por cabecera con valor por tenant, ruta con
  token opaco, límite de tasa, tope de cuerpo, relectura encolada y coalescida), que es el alcance
  completo de `reservations-webhooks`.
- **Y apuntarlo a un capturador de terceros no es aceptable**: este change midió que todo webhook
  de reserva lleva un objeto `guarantee` con `card_number`, `cvv` y `expiration_date`. Mandar eso
  a un *request bin* para medir latencia es un intercambio malo, y se decidió no hacerlo.
- **Lo que sí se dejó hecho para quien lo recoja**: `docs/channex-staging.md` documenta que los
  webhooks de Channex no van firmados, que la recomendación es una cabecera de secreto compartido
  propia, que hay reintentos con backoff hasta 10 intentos, que llegan **desordenados** (literal:
  *"Sequence of incoming webhook calls can be different from sequence of events which trigger that
  calls"*), y que **Channex sí tiene API para configurarlos** —incluido `is_global`—, a diferencia
  de Beds24. Eso es la entrada de diseño; falta solo el payload de ejemplo.
- **Dueño**: `reservations-webhooks`. No bloquea el PR de este change.

---

## Deuda con dueño que este change deja anotada

No son bloqueos —no impiden nada— pero se pierden si no constan en algún sitio que alguien lea:

1. 🔴 **`sdd/steering/security.md` necesita una regla de datos de titular de tarjeta**, y debe
   aterrizar **antes** de que `reservations-webhooks` o `pms-beds24-adapter` lleguen a
   `/sdd:design`, porque el hueco es una suposición de tiempo de diseño. Detalle completo y las dos
   propiedades que la regla necesita: `proposal.md`, sección "Affected specs".

2. **La estabilidad de `unique_id` entre revisions sigue sin verificar**, y sostiene la
   idempotencia por `(tenant_id, external_pms_id)` de todo el sistema. Las cuatro vías cerradas
   están documentadas en `docs/channex-staging.md`; `pms-beds24-adapter` debe comprobarlo antes de
   construir deduplicación encima.

3. **El puerto no tiene canal para reportar filas no mapeables.** `unmappable_rows` está declarado
   en `PMSAdapter` como stopgap; lo estructuralmente correcto es ensanchar el tipo de retorno como
   hace `ParseResult` en `ReservationCsvParser`. Dueño: `pms-beds24-adapter`, que ya posee la
   reestructuración del puerto por ADR 0006 decisión 3.

4. **Fuera del alcance de este change**: `sdd/project.md` afirma que «`uv` no está instalado en el
   host» y es falso (`/Users/hardcode/.local/bin/uv`). Corregirlo ahorra el descubrimiento en cada
   run futuro.
