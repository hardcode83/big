# reservation-create-web

[FE] **crear, modificar y cancelar una reserva desde `/reservations`**, que hoy es sólo lectura.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04). Es la única forma de **empezar** un ciclo nuevo sin OTA, sin PMS y sin `curl`.

**El hecho medido (2026-09-04)**: `backend/app/reservations/api/router.py` sirve `POST` (:90),
`PATCH` (:154) y `DELETE` (:180); `frontend/features/reservations/data/http/http-reservations-source.ts`
sólo tiene los dos `GET` (:115, :145). `reservations-web` lo dejó fuera por escrito
(`sdd/roadmap.md`, entrada `reservations-web`: *«Fuera de alcance: `POST`, `PATCH` y `DELETE`
—que la API sí sirve—, edición y cancelación desde la web»*) y no registró el seguimiento. La
importación CSV (`integrations/api/router.py:71`) tampoco tiene pantalla.

**Por qué no es cosmético**: hoy una reserva sólo nace por el seed, por CSV a mano o por `POST`.
El manager no puede iniciar una estancia nueva desde el navegador, así que cualquier prueba de
producto se limita a **replicar las tres estancias sembradas**. El resto del ciclo —jobs de
reloj, limpieza automática al checkout, portal del huésped, incidencias— ya está entregado y
espera a que exista la fila. Con el `MockPMSAdapter` como proveedor por defecto y la decisión de
**no reactivar Beds24 hasta la ventana de corte OTA** (2026-09-04), esta pantalla es la fuente
de reservas del MVP, y lo que el PRD §5.4 y DoD §28.4 previeron: «las reservas pueden crearse
manualmente y/o importarse via MockPMSAdapter o CSV».

**Alcance**: formulario de alta en `/reservations` y controles de modificar/cancelar en
`/reservations/[id]`, para `MANAGE_RESERVATIONS` (manager; el owner es lectura,
`policy.py:343-383`). Campos: propiedad, huésped (nombre, email, teléfono, idioma), fechas,
horas opcionales, adultos/niños, canal, importe/divisa opcionales, peticiones especiales. Nada
de backend.

**Lo que decide y no es cosmético**, todo medido en la auditoría y en RUNBOOK-seed-demo §5:

1. **Canal**: `POST` sólo admite canales manuales (`DIRECT`/`MANUAL`); la pantalla no ofrece
   `AIRBNB`/`BOOKING` — esos los trae el ingestor. Decirlo en la UI evita el `422`.
2. **Nace `PENDING`**, no `CONFIRMED`, y `status` es parcheable (`reservations/api/schemas.py:75-79`).
   El design decide si el formulario ofrece «crear confirmada» (dos llamadas) o si confirmar es
   un botón aparte en el detalle; sin `CONFIRMED` los jobs de reloj no la tocan.
3. **No hay reserva para hoy**: la API la rechaza (trampa documentada en RUNBOOK-seed-demo §5).
   El formulario lo valida en cliente con el mismo mensaje, y **no** intenta rodearlo: para
   comprimir el tiempo está `sim-advance`, no una fecha falsa.
4. **Las horas son en la zona de la propiedad** y la VM está en UTC (`state_resolution.py:40-64`).
   La UI muestra la zona junto al campo; `default_check_in_time`/`default_check_out_time` de la
   propiedad son el valor por defecto.
5. **Guest**: `POST` crea o reutiliza `Guest` por email (`ingest.py:263-287` para el ingestor;
   comprobar la ruta manual). La pantalla no gestiona huéspedes; sólo teclea sus datos. Los
   documentos de identidad los pone el huésped en el portal, nunca el manager.
6. **Cancelar ≠ borrar**: `DELETE` es cancelación con evento (`specs/reservations.md:226-228`).
   La UI lo llama «cancelar» y pide motivo si el contrato lo admite.
7. **Los `INGEST_OWNED_FIELDS`** (`reservations/domain/entities.py:63-81`): sobre una reserva
   que vino del PMS, editar fechas desde la UI es pelearse con el próximo sync. El detalle
   deshabilita esos campos cuando `channel` no es manual y lo explica.

**Va detrás de `reservations-identity-web`**: no tiene sentido construir el alta sobre una lista
que aún pinta el UUID de la vivienda (`reservations-view.tsx:159`) cuando el backend ya sirve
`property_name` y `guest_full_name`.

**Fuera de alcance**: pantalla de importación CSV (candidata aparte si se necesita); cualquier
proveedor real; edición de huésped como entidad; disponibilidad/solapes (no hay `get_availability`
en el puerto, `docs/beds24-adapter.md:167-172`).
