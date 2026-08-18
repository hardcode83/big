# Beds24 — adapter de producción

Cómo se opera la integración real con Beds24, el proveedor PMS/Channel Manager que
[ADR 0006](adr/0006-pms-channel-manager-provider.md) elige para el MVP. El *qué hace* está en
`sdd/specs/pms-beds24-adapter.md`; esto es el *cómo se opera*.

No confundir con [`beds24-spike.md`](beds24-spike.md), que documenta el **banco de medición**
(`backend/scripts/beds24_probe.py`) y sus hallazgos. Aquel mide el proveedor; este lo integra.

---

## Contrato de alta: una vivienda = una *property* de Beds24

**Cada vivienda de AutoHostAI debe ser una `property` distinta en Beds24**, y su `propertyId` es
lo que va en `properties.pms_external_id`.

No es una recomendación de estilo. El emparejamiento de reservas usa ese identificador, y si dos
viviendas lo comparten —lo que pasaría al montarlas como dos *rooms* de una misma property— el
sync **falla entero** con `AmbiguousPropertyExternalIdError` en vez de adjudicar una reserva al
piso equivocado. Falla ruidosamente y no corrompe datos, pero no sincroniza.

Tiene coste asociado y es deliberado: Beds24 factura por propiedad, así que este contrato es la
base del ~€21/mes que ADR 0006 calculó para las dos viviendas de Madrid.

**El mapeo a Booking.com no se puede hacer por API** (*"Mapping to booking.com cannot be done via
our API"*), así que el alta de cada propiedad en ese canal lleva un paso humano en el panel.

---

## Aprovisionar una propiedad

Tres cosas, y ninguna se hace por SQL a mano — eso se salta el cifrado, el guard cross-tenant y
la auditoría de golpe.

### 1. La credencial de cuenta

Beds24 autentica con un **refresh token de cuenta**: un solo valor que da acceso de **escritura
sobre todas las propiedades de esa cuenta**. Es la clase más peligrosa de credencial, no la
menos, y vive cifrada con Fernet en `pms_credentials` bajo la regla 3 de
`sdd/steering/security.md`.

El procedimiento exacto vive en **[`pms-credentials.md`](pms-credentials.md)** y no se repite
aquí. Lo único específico de Beds24 son las coordenadas: proveedor `beds24`, scope `account`.

```bash
read -rs PMS_CREDENTIAL_SECRET && export PMS_CREDENTIAL_SECRET
docker compose exec -e PMS_CREDENTIAL_SECRET backend \
  python -m app.integrations.cli.pms_credentials set <tenant-uuid> beds24 account
unset PMS_CREDENTIAL_SECRET
```

`read -rs` y **no** `PMS_CREDENTIAL_SECRET='…' docker compose …`: el segundo aterriza literal en
`~/.zsh_history`, que es la otra mitad exacta del motivo por el que el comando no acepta el
secreto como argumento. El `-e` es obligatorio — `docker compose exec` no reenvía el entorno del
host sin él.

**No hay ninguna variable de entorno de credencial de Beds24 en la aplicación.**
`BEDS24_REFRESH_TOKEN` existe solo para el banco de medición de `scripts/`, y son cosas
distintas: dos casas para una credencial es cómo una de las dos deja de rotarse.

### 2. El proveedor de la propiedad

`properties.pms_provider = BEDS24`. Una propiedad sin proveedor resuelve al mock, que es lo que
mantiene el arranque local y la suite sin depender de configuración.

### 3. El identificador de la propiedad

`properties.pms_external_id = <propertyId de Beds24>`. Lo lista
`GET /properties` (o `beds24_probe.py`, que ya lo hace con la guarda de cuenta puesta).

---

## Sincronizar

```bash
docker compose exec backend python -m app.integrations.cli.pms_sync <tenant-uuid>
```

El comando agrupa las propiedades del tenant **por proveedor** y hace una llamada por proveedor
distinto, no una por propiedad — con 12 propiedades, una llamada por propiedad consumiría el 96 %
de la cuota de créditos. Un proveedor que falla se registra en el informe y no impide que los
demás sincronicen; el comando sale con código **3** si alguno falló.

### Qué ve un sync, y por qué importa

`list_reservations(since)` pide por **fecha de modificación**, así que devuelve las reservas
creadas, **modificadas y canceladas** desde ese instante. Es la diferencia con el adapter de
Channex, que solo puede filtrar por fecha de creación y por tanto nunca ve una cancelación de una
reserva anterior — útil para validar el backend, inservible como sync de producción.

**Verificado contra la cuenta real el 2026-08-06**: ciclo crear → modificar → cancelar, con la
reserva visible en las tres comprobaciones.

> ⚠️ **Y hace falta pedir las canceladas explícitamente.** El listado por defecto **las omite**:
> el mismo ciclo, sin enumerar `status`, deja de ver la reserva justo al cancelarla. El adapter
> envía siempre los cinco estados que son reservas (`new`, `request`, `confirmed`, `cancelled`,
> `inquiry`) en parámetros repetidos — la forma con comas da `400`, y `includeCancelled=true` se
> ignora en silencio. Si alguien «simplifica» esa lista, el sync deja de enterarse de las
> cancelaciones sin que falle nada.
>
> Excluir `black` de esa enumeración es lo que mantiene los bloqueos de calendario fuera de la
> respuesta. Como es una allowlist, un estado que Beds24 añada en el futuro no llegaría hasta
> que se añada aquí.

### Bloqueos de calendario

Beds24 sirve los bloqueos del propietario por el **mismo endpoint** que las reservas, con
`status: black`. El adapter los excluye y **cuenta cuántos** en el log: importarlos crearía
estancias fantasma con huésped inventado que moverían la `PropertyStateMachine`.

---

## Créditos: leer el log

Beds24 factura por crédito con coste **dinámico y no publicado**, con una ventana de **100
créditos / 300 s por cuenta**. El adapter emite una línea por petición:

```
beds24: GET /bookings status=200 cost=1 remaining={'x-five-min-limit-remaining': '96.8'}
```

- **`cost=unknown`** no es `cost=0`. Un coste desconocido y uno nulo llevan a presupuestos
  distintos, así que nunca se registra un ausente como gratis.
- El coste llega **decimal**: las escrituras cuestan fraccionariamente.
- Un **429** detiene el sync con `PmsUnavailableError` y **no se reintenta**. La cuota es por
  cuenta, así que reintentar compite con el sync legítimo y con cualquier otro consumidor.

**La cadencia máxima sostenible está medida, y esta página no la repite**: sale de
[`beds24-spike.md`](beds24-spike.md), que la genera desde el registro commiteado. Aquí estaba
copiada y se quedó obsoleta dentro del mismo change que la corrigió, así que ahora se enlaza.

Lo que sí conviene tener delante al leerla: **es un techo de cuota, no una cadencia
recomendada.** El proveedor desaconseja el tiempo real y sugiere ~6 h. Lo que ese número aporta
es holgura, no permiso.

---

## Rotar la credencial

```bash
read -rs PMS_CREDENTIAL_SECRET && export PMS_CREDENTIAL_SECRET
docker compose exec -e PMS_CREDENTIAL_SECRET backend \
  python -m app.integrations.cli.pms_credentials rotate <tenant-uuid> beds24 account
unset PMS_CREDENTIAL_SECRET
```

**Medido: el refresh token de Beds24 no rota al usarse**, así que basta guardarlo una vez.

Si algún día el proveedor devolviera uno nuevo en el canje, el adapter **falla en duro** con un
mensaje que apunta a este comando, y no persiste el valor nuevo. Es deliberado: escribir la
credencial desde el adapter lo convertiría en una segunda vía de aprovisionamiento, y el CLI es
la única por diseño. Fallar es además la dirección segura — la alternativa es que la cuenta se
bloquee sola a los 30 días sin que nadie se entere.

---

## Qué NO hace este adapter

- **Mensajería.** `PMSMessagingPort` sigue vacío; `get_messages`/`send_message` llegan con
  `beds24-messaging-adapter`, que espera a que haya canales OTA conectados — sin canal no hay
  conversación que leer ni reserva de OTA a la que responder.
- **Recibir webhooks.** El endpoint entrante y la regla 12 son de `reservations-webhooks`.
- **Escribir en el proveedor.** Este adapter es enteramente de lectura: el puerto declara
  `list_reservations` y `get_reservation`, ambos `GET`. El hallazgo de que Beds24 responde `201`
  aunque rechace una escritura está implementado en el cliente —el veredicto se lee del cuerpo,
  también en las lecturas— pero su primer consumidor de escritura nace con la mensajería.
- **Precios y disponibilidad.** `update_price`, `block_dates` y `get_availability` llegan con
  **un change de ARI propio, cuando exista quien las consuma** — no con pricing.
  `revenue-pricing` (2026-08-18) implementó el Modo 1 del PRD §19: el sistema **recomienda un
  precio y no lo publica**; lo aprueba una persona y lo sube ella a la OTA, y por eso
  `PriceRecommendation` tiene el estado `APPLIED_EXTERNAL`. Así que pricing nunca llegó a
  necesitar escribir un precio en el proveedor.

---

## Referencias

- [`beds24-spike.md`](beds24-spike.md) — banco de medición, runbook de la cuenta y hallazgos.
- [ADR 0006](adr/0006-pms-channel-manager-provider.md) — por qué Beds24, y las cinco obligaciones
  de sus credenciales.
- `sdd/specs/pms-provider-resolution.md` — la resolución por propiedad y el CLI de credenciales.
- `sdd/steering/security.md` — reglas 3 (cifrado de credenciales), 9 (auditoría) y 13 (datos de
  tarjeta).
