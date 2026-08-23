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
`backend/app/auth/domain/policy.py:330`), y con ellos **cuatro** estaban servidas el 2026-08-19. El
mismo criterio que partió `cleaner-app` el 2026-08-18 —y por la misma causa: una entrada `[FE]`
cuyo rol no puede llamar lo que la pantalla necesita mostrar.

**Estado a 2026-08-23: el backend está completo y esta entrada ya es `[FE]` de verdad.** Las tres
entradas `[BE]` que salieron de aquí están las tres archivadas —`tech-incident-context`
(2026-08-22), `tech-cycle-completion` (2026-08-23) y `incident-photos` (2026-08-23)—, así que la
columna «Hoy» del censo no tiene ni un ❌. Lo que queda es pintar las pantallas; el rol
`TECHNICIAN` sigue con los mismos cinco permisos y ninguna de las tres los amplió.

Censo, medido contra `sdd/specs/maintenance.md` R6/R8,
`sdd/specs/tech-incident-context.md`, `sdd/specs/incident-photos.md` y
`backend/app/maintenance/api/schemas.py`:

| PRD §12 pide | Hoy | A quién le toca |
|---|---|---|
| incidencias asignadas | ✅ `GET /api/v1/incidents`, acotado por rol del token (R8) | `tech-app` |
| severidad y descripción | ✅ `IncidentResponse` incluye `description` a propósito | `tech-app` |
| botones aceptar / en ruta / finalizar | ✅ `accept`, `en-route`, `wait-parts`, `resume`, `resolve` | `tech-app` |
| cerrar incidencia con coste | ✅ `resolve` exige `final_cost` (R6) | `tech-app` |
| dirección de la propiedad | ✅ `GET /incidents/{id}/context` la proyecta sin `READ_PROPERTIES`, entregado por `tech-incident-context` | `tech-app` |
| instrucciones de contacto/acceso | ✅ ídem, con `properties.access_notes` en la tabla de sumideros de `steering/security.md` (excepción 6) | `tech-app` |
| notas del propietario/manager | ✅ la nota de la asignación, en la misma proyección | `tech-app` |
| fotos del incidente | ✅ `GET /incidents/{id}/photos` bajo `READ_INCIDENTS`, entregado por `incident-photos` | `tech-app` |
| subir fotos finales (antes/después) | ✅ `POST /incidents/{id}/photos` con `stage` `BEFORE`/`AFTER` bajo `EXECUTE_INCIDENTS` | `tech-app` |
| botón **rechazar** | ✅ `POST /incidents/{id}/reject`, entregado por `tech-cycle-completion` | `tech-app` |
| campo **ETA** | ✅ `incidents.eta_at`, opcional en `accept` y en `en-route` | `tech-app` |
| **materiales** | ✅ `incidents.materials`, opcional en `resolve` | `tech-app` |

## Precisiones que evitan rehacer el análisis

**«En ruta» ya está entregado** (2026-08-22, `tech-cycle-completion`). Se resolvió por la segunda
vía: `start` pasó a llamarse `en_route` conservando exactamente sus orígenes (`ACCEPTED`) y su
destino (`IN_PROGRESS`), y escribe `TECHNICIAN_EN_ROUTE`. No se retiró nada del vocabulario, porque
`resume_work` (`WAITING_EXTERNAL_PARTS → IN_PROGRESS`) conservó `TECHNICIAN_STARTED`. Para esta
entrada eso significa que **el botón «en ruta» tiene ruta propia** —`POST
/incidents/{id}/en-route`— y que la ruta `/start` ya no existe en el contrato publicado: quien
teclee el cliente contra una copia vieja de `openapi.json` recibirá un `404`.

**Rechazar no es cancelar, y ya existe.** `cancel` es del manager (`_INCIDENT_MANAGE`) y lleva la
incidencia a un terminal. Lo que PRD §6 le concede al técnico («aceptar/rechazar tickets») es
devolverla al manager para reasignación, y eso es lo que hace `reject`
(`ASSIGNED`/`ACCEPTED → CLASSIFIED`, bajo `EXECUTE_INCIDENTS`), entregado por
`tech-cycle-completion`. Lo que le queda a esta entrada es la UX: el rechazo **borra los tres
campos de la asignación** —asignatario, ETA y nota del manager—, así que la pantalla no puede
seguir mostrándolos después de un rechazo con éxito, y notifica al manager por su cuenta.

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

**Las fotos ya están entregadas** (2026-08-23, `incident-photos`), y lo que queda para esta
entrada es sólo la pantalla. Hay tres rutas y una entidad: `POST /api/v1/incidents/{id}/photos`
(`multipart/form-data` con `stage` y `file`, bajo `EXECUTE_INCIDENTS`, sólo con la incidencia en
`IN_PROGRESS` o `WAITING_EXTERNAL_PARTS`), `GET /api/v1/incidents/{id}/photos` (bajo
`READ_INCIDENTS`, de la más antigua a la más reciente) y `GET /api/v1/incident-photos/{photo_id}`,
**anónima a propósito**, que es la que el `<img src>` resuelve. El detalle está en
`sdd/specs/incident-photos.md`.

Tres cosas que la pantalla no debe volver a decidir y sí tiene que respetar:

- **La `url` que devuelve la respuesta es de un solo uso práctico**: es una URL firmada acuñada
  para *esa* respuesta y con caducidad acotada. La pantalla la usa tal cual y **no** la persiste ni
  la comparte; cuando caduque, se vuelve a listar. No hay `storage_key` en ningún cuerpo.
- **Las etapas son exactamente dos**, `BEFORE` y `AFTER`, y son un enum cerrado: un tercer valor
  responde `422`. No hay campo de texto libre de tipo de foto, a diferencia del `photo_type` de
  limpieza.
- **No hay puerta de evidencia en `resolve`**: la foto de cierre es opcional, así que la pantalla no
  puede prometer que sin ella el cierre falla. Y **no hay borrado** por ninguna vía de la API: una
  foto subida por error se queda.

Lo que sigue siendo cierto del análisis original: `incident-photos` **no** decidió proveedor ni
esquema de claves ni firma — eso lo cerraron `cleaning-photos-storage` y
`object-storage-provisioning`.

**Lo que `tech-app` no tiene que volver a decidir.** El umbral de aprobación de la propietaria
(PRD §11/§12, `TenantConfig.owner_approval_threshold_eur`) lo resuelve el backend en la segunda
puerta de R4: cerrar con un `final_cost` por encima del umbral **no** resuelve la incidencia, la
manda a `AWAITING_OWNER_APPROVAL` y el técnico tendrá que repetir el cierre. La app lo **muestra**;
no lo calcula ni lo evita.

**El andamio del frontend ya existe.** `frontend/app/(field)/tech/{page,layout,error}.tsx` y
`frontend/app/(field)/tech/incidents/[id]/page.tsx` están puestos, con `TechnicianShell` y
`AuthGuard`, y las dos páginas son `RoutePlaceholder`. `tech-app` los sustituye; no crea el
segmento ni el shell.
