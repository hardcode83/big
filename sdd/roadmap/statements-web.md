# statements-web

[FE] **`/statements`, hoy `RoutePlaceholder` sobre un backend entregado**.

> Hito «MVP operable» 3 — *autoservicio del tenant* (auditoría del 2026-09-04). Cierra
> DoD §28.16 desde el navegador.

**El hecho medido (2026-09-04)**: `frontend/app/(workspace)/statements/page.tsx:11` es un
`RoutePlaceholder`. `revenue-statements` (archivado 2026-09-02, `sdd/specs/revenue-statements.md`)
entregó once rutas en `backend/app/statements/api/router.py` —statement mensual por propiedad,
gastos, desglose por reserva, export CSV, PDF— y el job `generate_owner_statements` corre el día
1 de cada mes a las 02:00 UTC con candado de 6 h (`scheduler/schedule.py:132-139`). **Ningún
fichero del frontend las llama.** El permiso ya está repartido: `READ_STATEMENTS` para el owner,
gestión para el manager (`auth/domain/policy.py:343-421`). Ni `revenue-statements` ni el
roadmap registraron la mitad `[FE]`.

**Por qué no es cosmético**: DoD §28.16 —«el statement mensual puede generarse y exportarse a
CSV»— se cumple hoy sólo por API; y es la pantalla que el owner mira una vez al mes para saber
qué ha ganado, la razón de ser del rol (PRD §20, §1 «Propietaria»). Además `revenue-statements`
fue el change que **necesitó `backend-pyright-tooling`** para poder cerrarse: dejar su frontend
sin registrar es tirar la mitad del esfuerzo.

**Alcance**: `/statements` con lista de statements por propiedad y mes, detalle con el desglose
por reserva y los gastos, y **descarga** de CSV y PDF. Para owner y manager según permiso.
Generación a mano de un statement (si la API lo permite fuera del job) sólo si el design lo acota.
Sin backend, salvo lo que la descarga exija (abajo).

**Lo que decide y no es cosmético**:

1. **La primera descarga de fichero del workspace.** Las fotos ya sirven bytes con URL firmada y
   `Cache-Control` privado (`specs/file-storage.md`, `test_serve_photo_api.py`); el CSV/PDF de un
   statement lleva importes del owner y es igual de privado. Heredar esa forma —no un `<a href>`
   a una ruta autenticada por cookie que no existe (la sesión vive en memoria,
   `frontend-auth-session`)—. Medir cómo sirve hoy `router.py` el CSV antes de decidir.
2. **Gastos**: crear/editar `Expense` desde la UI es una mutación con importe y texto libre;
   si entra, hereda `storable_text` y el acoplamiento con `reconcile_owner_approvals_for_expenses`
   (cada 5 min, `schedule.py:69`). Recomendación: lectura en este change, alta de gastos como
   candidata `expenses-web`.
3. **Divisa y nulos**: `reservation-amount-empty-render` ya enseñó la forma (`?? "—"`, nunca
   « EUR» suelto). Mismo idioma.
4. **Regla 11**: un statement agrega importes de N reservas para un permiso que ya los podía leer
   uno a uno; el precedente de `dashboard-activity-feed` dice que eso **no** estrena audiencia y
   no añade fila al censo. El design lo cita para que el panel no lo reabra.

**Fuera de alcance**: facturación fiscal (non-goal PRD §29); alta de gastos; envío del statement
por email al owner (candidata cuando exista `guest-scheduled-comms`, que es quien fija la forma
de un correo con contenido).
