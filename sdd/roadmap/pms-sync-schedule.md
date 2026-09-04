# pms-sync-schedule

[BE] **el sync periódico del PMS que hoy no existe**.

> Hito «MVP operable» 3 — *autoservicio del tenant* (auditoría del 2026-09-04). Con `mock` y
> Channex es un change S; con Beds24 vivo es el mismo change con un número distinto.

**El hecho medido (2026-09-04)**: `backend/app/scheduler/schedule.py` —`CADENCES` (:46-76),
`DAILY_JOBS` (:102-106), `MONTHLY_JOBS` (:132-139), `ON_DEMAND_TASKS` (:156)— no contiene ningún
sync de PMS. El único vecino es `process_webhook_events` cada 60 s (:58), que **re-lee por API lo
que un aviso nombra**, no barre. `python -m app.integrations.cli.pms_sync <tenant> [window-days]
[--provider]` es «**the only way to run a sync, and that is deliberate**»
(`integrations/cli/pms_sync.py:7-19`): `celery-jobs` design D16 decidió no programarlo porque la
cadencia es función del presupuesto de créditos de Beds24 —100 créditos / 300 s por cuenta, coste
por petición no publicado— que no está medido (`docs/beds24-adapter.md:113-135`). Y el propio
router de webhooks nombra el poll como **camino de recuperación** de los avisos perdidos durante
una rotación (`integrations/api/router.py:153-156`) sin que nada lo programe. No hay `make pms-sync`.

**Por qué no es cosmético**: la frase de `steering/product.md:9` —*el PMS es la fuente de verdad
de reservas*— es hoy verdadera sólo mientras alguien ejecute un comando. Sin barrido, un webhook
perdido es una reserva que no existe hasta el siguiente `pms_sync` a mano; con Beds24, cuyos
webhooks **no van firmados** y se configuran por propiedad desde su UI (ADR 0006), «alguno se
pierde» es el caso normal, y Beds24 mismo «desaconseja el tiempo real y recomienda sincronización
completa cada ~6 horas». El argumento de D16 —no fijar una cadencia sin medir el coste— es
correcto para Beds24 y **no aplica** a `MockPMSAdapter` ni a Channex staging, que son los
proveedores con los que el MVP va a operar hasta la ventana de corte.

**Alcance**: (1) una tarea de beat `sync_pms_reservations` en `DAILY_JOBS` o con cadencia
propia, que recorra los tenants y ejecute `SyncReservationsFromPmsUseCase`
(`integrations/application/use_cases.py:76-207`) **por tenant, con sesión marcada a ese tenant,
nunca re-marcada** —obligación 5 de ADR 0006 y el precedente de `pms_sync <tenant>` y de
`webhook_events`—, agrupando por proveedor como el caso de uso ya hace (:342-355); (2) candado
de `scheduler/locks.py` con TTL derivado como los demás (`schedule.py:9-12`); (3) la cadencia
como `Settings` con default **6 h** y la ventana (`window-days`) como setting; (4) `make pms-sync`
como disparo a mano, con la misma forma `python -m` de los otros comandos; (5) el informe del sync
(`created/updated/skipped/failures`) a log estructurado, y la fila de `PMS_CREDENTIAL_READ` que
el caso de uso ya escribe (:306-339) sigue igual.

**Lo que decide y no es cosmético**:

1. **Qué tenants**: todos los `ACTIVE` con al menos una propiedad con `pms_provider` distinto de
   `MOCK`? ¿O también `MOCK`, para que dev y demo ejerciten el camino? Recomendación: todos, y
   que el mock siga siendo idempotente (`skipped`, no `updated`, `ingest.py:218-228`), que es lo
   que prueba que el job no rompe nada.
2. **Créditos**: el design deja el gancho para que la cadencia baje a Beds24 cuando
   `beds24-webhook-cutover-measurement` mida `X-RequestCost`; hasta entonces 6 h y un aviso en
   log si `failures` trae un `429`/cuota.
3. **Credenciales por propiedad**: el caso de uso **se niega en voz alta** a servirlas en un sync
   agrupado (:229-246, apunta al `BLOCKED.md` de `pms-provider-resolution`). Hoy todas son de
   cuenta (`BEDS24 → ACCOUNT`, `enums.py:77-79`), así que no muerde; el job hereda la negativa y
   no la resuelve.
4. **Un `TimelineEvent` por reserva modificada/cancelada no existe** (`pms-ingest-change-events`):
   con el sync programado el hueco pasa de teórico a diario. Esa entrada va detrás de ésta y el
   design de ésta la nombra como el precio conocido.

**Fuera de alcance**: ARI (`update_price`, `block_dates`, `get_availability` no están en el
puerto); mensajería OTA (`beds24-messaging-adapter`); ruta HTTP de sync (PRD §23 no la define,
`pms_sync.py:1-6`); reactivar la cuenta de Beds24.

**Verificación**: con el stack local, `beat` dispara el job, el informe sale en el log del
worker con `skipped = 2` para el mock (las dos reservas del seed ya existen), y `make pms-sync`
produce el mismo informe a mano. Y la guardia de aislamiento: dos tenants con `MOCK`, cada uno
ve sólo sus filas.
