# tech-app

[FE] la app del técnico, mobile-first: `/tech` y `/tech/incidents/[id]` (PRD §26.20, §24).

> Esta nota se escribió el 2026-08-19, al abrir el `/sdd:new` de `tech-app` y **cerrarlo sin
> proposal**: la entrada no era implementable como `[FE]`. La miden las tres entradas `[BE]` que
> salieron de aquí —`tech-incident-context`, `incident-photos` y `tech-cycle-completion`— y la lee
> el `/sdd:new` de cada una de las cuatro.

## Por qué se partió

PRD §12 «UI del técnico» enumera **once** cosas. El rol `TECHNICIAN` tiene exactamente cinco
permisos (`_SELF_SERVICE` + `_INCIDENT_EXECUTE` = `READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
`READ_OWN_NOTIFICATIONS`, `READ_INCIDENTS`, `EXECUTE_INCIDENTS`, en
`backend/app/auth/domain/policy.py:330`), y con ellos **cuatro** de las once están servidas. El
mismo criterio que partió `cleaner-app` el 2026-08-18 —y por la misma causa: una entrada `[FE]`
cuyo rol no puede llamar lo que la pantalla necesita mostrar.

Censo, medido contra `sdd/specs/maintenance.md` R6/R8 y
`backend/app/maintenance/api/schemas.py`:

| PRD §12 pide | Hoy | A quién le toca |
|---|---|---|
| incidencias asignadas | ✅ `GET /api/v1/incidents`, acotado por rol del token (R8) | `tech-app` |
| severidad y descripción | ✅ `IncidentResponse` incluye `description` a propósito | `tech-app` |
| botones aceptar / en ruta / finalizar | ⚠️ `accept`, `start`, `wait-parts`, `resume`, `resolve` | `tech-app` |
| cerrar incidencia con coste | ✅ `resolve` exige `final_cost` (R6) | `tech-app` |
| dirección de la propiedad | ❌ `property_id` es un UUID pelado y no hay `READ_PROPERTIES` | `tech-incident-context` |
| instrucciones de contacto/acceso | ❌ `properties.access_notes` detrás de ese mismo permiso | `tech-incident-context` |
| notas del propietario/manager | ❌ no hay columna en `Incident` (PRD §7.13) | `tech-incident-context` |
| fotos del incidente | ❌ no hay entidad ni ruta | `incident-photos` |
| subir fotos finales (antes/después) | ❌ ídem; PRD §6 se las concede al rol | `incident-photos` |
| botón **rechazar** | ❌ no hay transición `reject`; PRD §6 sí se la concede | `tech-cycle-completion` |
| campo **ETA** | ❌ no hay columna | `tech-cycle-completion` |
| **materiales** | ❌ solo `final_cost` | `tech-cycle-completion` |

## Precisiones que evitan rehacer el análisis

**«En ruta» no está entregado, y está a medio declarar.** `TimelineEventType.TECHNICIAN_EN_ROUTE`
existe en el vocabulario y `sdd/specs/maintenance.md` § Estado dice literalmente que **nadie lo
escribe**: «no hay transición "en ruta" en el ciclo entregado». `start` (`ACCEPTED → IN_PROGRESS`)
es lo más parecido y escribe `TECHNICIAN_STARTED`. Quien cierre `tech-cycle-completion` decide si
«en ruta» es un estado nuevo o si `start` pasa a significar eso — y en el segundo caso el evento
huérfano se retira, no se deja.

**Rechazar no es cancelar.** `cancel` existe pero es del manager (`_INCIDENT_MANAGE`), y lleva la
incidencia a un terminal. Lo que PRD §6 le concede al técnico («aceptar/rechazar tickets») es
devolverla al manager para reasignación, no cerrarla. La tabla de transiciones de R1 admite
`assign` desde `ASSIGNED`, así que el destino natural existe; lo que no existe es la operación.

**La decisión de la regla 11 aparcada se dispara aquí, y no se disparó en `cleaner-task-context`.**
Aquella proyección **excluyó** `access_notes`, `cleaning_notes` y `emergency_notes` de forma
estructural y dejó dicho por qué no la disparaba: «lo que la dispara es que el conjunto de lectores
de una de esas columnas crezca a un rol que hoy no la tiene, y esta proyección no lee ninguna de
las cuatro» (`sdd/specs/cleaner-task-context.md`). PRD §12 **sí** pide al técnico «instrucciones de
contacto/acceso», así que `tech-incident-context` es previsiblemente el change que tiene que meter
`properties.access_notes` en la tabla de sumideros de `steering/security.md` y decidir la forma
(cifrado en reposo, exclusión de listados, o ambas). Coordinar con `sdd/roadmap/cleaner-app.md`,
que tiene la misma decisión aparcada para `access_records.notes` y pide cubrir las cuatro columnas
a la vez o decir explícitamente por qué no.

**Las fotos tienen puerto y no tienen consumidor.** `sdd/specs/file-storage.md` nombra a
`maintenance` (fotos de incidente) como uno de sus dos siguientes consumidores, y es la razón
declarada de que la capability viva en `app/integrations/` y no colgando de `cleaning`. Es decir:
`incident-photos` **no** decide proveedor ni esquema de claves ni firma — eso está cerrado por
`cleaning-photos-storage` y `object-storage-provisioning`. Decide entidad, rutas, quién puede
llamarlas y el par antes/después.

**Lo que `tech-app` no tiene que volver a decidir.** El umbral de aprobación de la propietaria
(PRD §11/§12, `TenantConfig.owner_approval_threshold_eur`) lo resuelve el backend en la segunda
puerta de R4: cerrar con un `final_cost` por encima del umbral **no** resuelve la incidencia, la
manda a `AWAITING_OWNER_APPROVAL` y el técnico tendrá que repetir el cierre. La app lo **muestra**;
no lo calcula ni lo evita.

**El andamio del frontend ya existe.** `frontend/app/(field)/tech/{page,layout,error}.tsx` y
`frontend/app/(field)/tech/incidents/[id]/page.tsx` están puestos, con `TechnicianShell` y
`AuthGuard`, y las dos páginas son `RoutePlaceholder`. `tech-app` los sustituye; no crea el
segmento ni el shell.
