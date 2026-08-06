# BLOCKED — pms-provider-resolution

> **Ambos bloqueos resueltos el 2026-08-06 por Jose**: se toma la opción (a), agrupar por
> proveedor, y se implementa **en este change**. El detalle de la decisión queda abajo, tachado
> como histórico, porque el razonamiento —y sobre todo los números medidos que lo sostienen— es
> lo que hay que releer si alguien reabre la cadencia del sync. El fichero se borra al archivar.

## ~~1. ¿Cómo se abanica el sync cuando cada propiedad puede tener un proveedor distinto?~~ RESUELTO

**Decisión: (a) agrupar por proveedor, en este change.**

`SyncReservationsFromPmsUseCase.execute` llamaba **una sola vez** a `list_reservations(since)`
para todo el tenant y resolvía la propiedad de cada reserva por `pms_external_id`. Esa forma
presupone **un adapter por ejecución**, que es lo que R2.2 retira.

Lo que decidió entre las dos opciones, y conviene no volver a derivarlo:

- **(b) una llamada por propiedad escala sin cota** con el portfolio. Con 12 propiedades en
  Beds24 un solo ciclo se come el **96% de la cuota** de 100 créditos / 300 s — medido sobre una
  cuenta **vacía** (`specs/pms-beds24-spike.md` avisa de que con reservas dentro sube), y el
  proveedor desaconseja explícitamente el tiempo real.
- **(a) agrupar escala con el número de proveedores distintos** que el tenant tenga configurados
  — 2-3 hoy, acotado por definición. Y como **todos** los proveedores evaluados autentican con
  credencial de cuenta, «una llamada por proveedor» **es** «una llamada por cuenta», que es
  exactamente la forma que el spike midió y validó como sostenible.
- **Diferirlo a `pms-beds24-adapter` era la secuencia más arriesgada**: dejaría un caso de uso que
  sigue asumiendo un adapter por ejecución, así que un tenant a mitad de migración —el escenario
  que ADR 0006 y este proposal nombran como motivo principal de R2— quedaría mal servido justo
  cuando la feature debería importar.

**Lo que la implementación añade y no estaba previsto en el design**: `PropertyRepository.list_all`
y `PMSAdapterFactory.provider_for`. El segundo es necesario porque el override `--provider` vive
en la factory: agrupar por `property.pms_provider` a secas ignoraría el override al agrupar y lo
aplicaría al resolver, que es una incoherencia silenciosa.

## ~~2. Dónde se escribe la fila de auditoría por ejecución~~ RESUELTO

Se escribe en `SyncReservationsFromPmsUseCase.execute`, al cerrar el run, una fila
`PMS_CREDENTIAL_READ` **por credencial distinta** descifrada — las que `CredentialReadLog`
acumula, deduplicadas.

**La granularidad exacta la fija la regla 9 de `steering/security.md`, y este fichero no la
reformula** — lo intentó dos veces y las dos se quedaron obsoletas cuando la regla se corrigió.
Lo que sí aporta y es suyo: la medición de la que salió el debate, que un sync de N propiedades
servidas por una credencial de cuenta la descifra N veces, y que **hoy** solo un proveedor guarda
credencial (`BEDS24`), así que la repetición es en el tiempo y no en el portfolio.
