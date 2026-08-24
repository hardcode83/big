# cleaner-app

[FE] la app de la limpiadora, mobile-first: `/cleaner` y `/cleaner/tasks/[id]` (PRD §26.19, §24).

> Esta nota se escribió para `field-apps`, que el 2026-08-18 se partió en cuatro
> (`cleaning-manager-view`, `cleaner-app`, `tech-app`, `conversations-inbox`).
> La decisión que describe es de la app de la limpiadora —es la que muestra accesos a un
> rol que hoy no los ve—, así que viaja aquí entera y no a las otras tres.

## Hereda de `access-notifications` una decisión de steering pendiente

**`access_records.notes` no está en la tabla de sumideros de texto en claro de la regla 11**
(`sdd/steering/security.md`), y este change es el que probablemente tendrá que meterla.

Qué hay hoy: `notes` es texto libre que un operador teclea en la **misma petición** que el código
de acceso (PRD §15 lo pone en la firma del propio adapter, así que no se puede quitar sin
divergir). `AccessRecord.register_manual_code` rechaza la petición cuando el código aparece en las
notas —normalizando caja y separadores, tras dos rondas del panel de seguridad—, lo que cierra el
caso del operador descuidado. Lo que **no** cierra, y ninguna comprobación dentro de la petición
puede cerrar, es que alguien escriba *otro* código en `notes` más tarde.

Por qué cae aquí (razonamiento original, escrito cuando la entrada era `field-apps`): mientras `notes` solo lo vean el owner y el manager, el radio es el de quien ya
puede registrar el código. En cuanto la app de la limpiadora muestre accesos, la superficie crece
a un rol que hoy no tiene `READ_ACCESS_RECORDS` — y ahí el residual deja de ser aceptable.

Qué hacer entonces, según la propia regla 11 («con una entrada nueva y nombrada aquí, aprobada en
el design del change que la pida»): añadir `access_records.notes` a su tabla y decidir la forma —
cifrado en reposo, o exclusión de los listados, o ambas. La decisión la tomó Jose el 2026-08-08:
no en `access-notifications`, que no la necesita para cumplir su R2.6, sino aquí.

Precedente aplicable: `properties.access_notes` / `cleaning_notes` / `emergency_notes` estaban en la
misma situación —auditables pero no denylisted, con la disciplina en el caso de uso
(`properties-crud` design D7)—, así que la decisión debería cubrir las cuatro columnas a la vez o
decir explícitamente por qué no.

**Y una de las cuatro ya está decidida, así que esta nota ya no describe la decisión entera.**
`tech-incident-context` (2026-08-21) amplió el público de `properties.access_notes` al rol
`TECHNICIAN` y con ello le tocó decidir su forma: entró en la tabla de la regla 11 con **excepción
6** y con su mecanismo implementado —las **tres** notas de `properties` salieron del listado
paginado—, y dijo explícitamente por qué las otras dos no ganan fila del censo: no las lee ninguna
proyección nueva, así que no ganan lector, y su propósito no es transportar un valor de la regla 3.
Es el «decir explícitamente por qué no» que el párrafo anterior pedía, resuelto para tres de las
cuatro.

Lo que queda de esta nota, entonces, son **dos cosas y no una**:

- **`access_records.notes` sigue siendo de aquí**, con el razonamiento de arriba intacto: su
  mitigación actual (`AccessRecord.register_manual_code` rechaza la petición cuando el código
  aparece en las notas) no es trasladable a `access_notes`, porque allí no hay código en claro
  almacenado contra el que comparar. El disparador sigue siendo el mismo: que la app de la
  limpiadora muestre accesos.
- **La mitad de cifrado en reposo dejó de ser de esta nota** y vive en
  `sdd/roadmap/plaintext-sink-encryption-at-rest.md`, que cubre las cuatro columnas juntas —las
  tres de `properties` y esta— porque la amenaza que responde (lectura offline de la base, de un
  backup o de una réplica) es idéntica para todas y no la mueve ningún change de audiencia.
  `tech-incident-context` la rechazó con su motivo escrito, no por olvido.

---

## Lo que su `/sdd:new` verificó el 2026-08-23, y por qué se aplazó

Este `/sdd:new` **no escribió proposal**. Midió la entrada contra el código y encontró tres cosas;
la tercera la bloquea.

### 1. El backend ya alcanza casi todo PRD §11 — el censo, medido

`UserRole.CLEANER` sigue siendo `_SELF_SERVICE | _CLEANING_EXECUTE` en
`backend/app/auth/domain/policy.py`: `READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
`READ_OWN_NOTIFICATIONS`, `READ_CLEANING_TASKS`, `EXECUTE_CLEANING_TASKS`. Con esos dos últimos
alcanza, contado sobre `backend/openapi.json`:

| PRD §11 pide | Ruta | Permiso |
|---|---|---|
| propiedades asignadas | `GET /cleaning-tasks` | `READ_CLEANING_TASKS` |
| dirección | `GET /cleaning-tasks/{id}/context` | `READ_CLEANING_TASKS` |
| hora programada | `scheduled_start`/`scheduled_end` de `CleaningTaskResponse` | `READ_CLEANING_TASKS` |
| info de checkout previo | `checkout_at` de `/context` | `READ_CLEANING_TASKS` |
| deadline del próximo check-in | `next_checkin_deadline` de `/context` | `READ_CLEANING_TASKS` |
| checklist ítem a ítem con progreso | `GET /{id}/checklist` + `POST /{id}/checklist/{item_id}/complete` | `READ_` / `EXECUTE_` |
| **botones de subir foto por categoría** | `POST /{id}/photos` — pero **las categorías no se pueden enumerar** | ver §3 |
| botón «reportar incidencia» | `POST /{id}/incidents` | `EXECUTE_CLEANING_TASKS` |
| botón «finalizar limpieza» | `POST /{id}/complete` | `EXECUTE_CLEANING_TASKS` |

Más `accept`/`reject`/`start`, que PRD §6 concede al rol y el ciclo de `specs/cleaning.md` sirve.
Es decir: los dos repartos de 2026-08-18 (`cleaner-task-context`, `cleaner-incident-report`)
hicieron su trabajo. Ocho de las nueve líneas son alcanzables hoy.

Andamio ya en pie, para que el proposal futuro no lo redescubra: `CleanerShell`
(`features/shell/components/cleaner-shell.tsx`, topbar sin sidebar ni bottom-nav),
descriptores `cleaner` y `cleaner-task` en `navigation/route-registry.ts`, `error.tsx` de segmento,
y `app/(field)/cleaner/layout.tsx` = `CleanerShell` + `AuthGuard`. Las dos páginas son
`RoutePlaceholder`.

**Lo que NO se puede reusar de `cleaning-manager-view`**, aunque la tentación es directa:
`features/cleaning/data/http/http-cleaning-source.ts` resuelve nombres de propiedad y de limpiadora
pidiendo `GET /users?role=CLEANER` y el catálogo de propiedades — `READ_USERS` y `READ_PROPERTIES`,
ninguno de los cuales tiene `CLEANER`. La app de la limpiadora nombra su piso por `/context`, no por
un directorio.

**Y una tensión que el design tendrá que resolver**: `CleaningTaskResponse` lleva `property_id`
pelado y no el nombre, así que **nombrar el piso en el listado exige una llamada a `/context` por
tarea**. `specs/cleaner-task-context.md` lo dejó dicho a propósito — *«El contexto embebido en el
listado. `CleaningTaskPageResponse` no lo lleva: lo decidirá `cleaner-app` con una pantalla real
delante, y con 2 viviendas en el MVP N es 1-3»*. Sigue siendo de aquí.

### 2. El aterrizaje tras el login es un agujero real, y es de esta entrada

`features/auth/components/login-form.tsx` manda a **todo el mundo** a `/dashboard` (su
`safeReturnTo` cae ahí en los tres caminos), y `features/auth/components/auth-guard.tsx` es ciego al
rol: solo distingue `authenticated` de `anonymous`/`expired`. Una limpiadora que entra hoy aterriza
en una pantalla de perfil `workspace` que le contesta `403` en cada llamada, y `CleanerShell` no le
da navegación para salir de ahí.

Decisión de Jose el 2026-08-23: **entra en el alcance de `cleaner-app`** como requisito propio —
destino por rol tras el login (`CLEANER` → `/cleaner`), conservando el `returnTo` cuando es válido.
El mecanismo es un mapa rol→aterrizaje con **una sola entrada** distinta del default, calcando el
precedente que `policy.py` ya sienta para el mapa de `D18` de `messaging-ai` («the role→`sender_type`
map has a single entry. Whoever grants … adds the second»): la segunda entrada, `TECHNICIAN` →
`/tech`, la pone `tech-app`.

**Fuera de alcance, y nombrado**: una guarda de rol por ruta para los 12 destinos de `workspace`.
Eso decide RBAC de frontend para el shell entero, no para `/cleaner`.

### 3. Lo que la bloquea: las categorías de foto no son enumerables

PRD §11 pide «botones de subir foto por categoría». Las categorías viven **solo** en
`cleaning_checklist_templates.required_photos`, publicado en exactamente dos esquemas del contrato
—`ChecklistTemplateResponse` y `CreateChecklistTemplateRequest`— tras `READ_CLEANING_TEMPLATES` /
`MANAGE_CLEANING_TEMPLATES`, que `CLEANER` no tiene. `GET /{id}/checklist` devuelve solo
`ChecklistItemStateResponse[]`, sin tipos de foto. Así que la limpiadora puede subir con un
`photo_type` (404 si la plantilla no lo declara) y listar las ya subidas, pero no puede enumerar los
tipos, saber cuáles son `required: true` ni leer su `label`: solo los descubriría fallando el cierre
y leyendo el `409`.

Decisión de Jose el 2026-08-23: **tercer reparto de esta entrada por el mismo motivo**. Se registró
`cleaner-photo-requirements` `[BE]` —análisis entero en
[`cleaner-photo-requirements.md`](cleaner-photo-requirements.md)— y `cleaner-app` declara `needs:`
sobre ella. Este `/sdd:new` se retoma cuando esté entregada.

### 4. La decisión de la regla 11 sobre `access_records.notes` se queda **sin dueño**

Todo lo que este fichero dice arriba sobre `access_records.notes` era correcto **excepto su
disparador**, y el disparador es lo que la ataba aquí. El razonamiento original decía: *«En cuanto
la app de la limpiadora muestre accesos, la superficie crece a un rol que hoy no tiene
`READ_ACCESS_RECORDS`»*. Comprobado el 2026-08-23: **esta app no muestra accesos, y no puede.**

- PRD §11 «UI de limpiadora» enumera nueve cosas y ninguna es un acceso.
- PRD §6 concede al rol `CLEANER` siete capacidades y ninguna es ver accesos.
- `policy.py` lo deniega por escrito, no por olvido: *«Access records split read/manage … `CLEANER`/`TECHNICIAN` get neither — a guest's door code is not part of doing a cleaning or a repair.»*

Así que la premisa condicional nunca se cumple: `cleaner-app` no amplía el público de `notes`, y con
ello **la decisión de la regla 11 sobre `access_records.notes` deja de tener change asignado**. No
está resuelta ni retirada — está aparcada sin disparador, que es un estado distinto de «pendiente en
el change siguiente» y hay que decirlo así. Lo que la despertaría es una superficie nueva que dé
`READ_ACCESS_RECORDS` a un rol que hoy no lo tiene, y hoy no hay ninguna planificada. Su mitad de
cifrado en reposo sigue viva y con dueño, en
[`plaintext-sink-encryption-at-rest.md`](plaintext-sink-encryption-at-rest.md).

**Dos frases de spec viva quedan apuntando aquí y hay que corregirlas al archivar `cleaner-app`**
(se dejan intactas ahora porque `sdd/specs/` lo escribe `/sdd:archive`, no `/sdd:new`):

- `sdd/specs/cleaner-task-context.md` — *«…y `access_records.notes`, que sigue siendo de `cleaner-app`»*.
- `sdd/specs/access-notifications.md` — *«Anotado en la entrada de roadmap de `cleaner-app`, que es quien ampliará la superficie de `notes`»*.
