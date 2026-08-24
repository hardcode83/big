# cleaner-photo-requirements

[BE] Qué fotos pide la tarea de limpieza, dicho a quien tiene que subirlas.

> Separada de `cleaner-app` el **2026-08-23**, al abrir su `/sdd:new`. Es el **tercer** reparto de
> esa entrada por el mismo motivo, después de `cleaner-task-context` (2026-08-18) y
> `cleaner-incident-report` (2026-08-18): PRD §11 pide nueve cosas a la UI de limpiadora, y este
> es el punto que sigue no siendo alcanzable con los permisos que el rol tiene.

## El hueco, medido

PRD §11 «UI de limpiadora» pide literalmente **«botones de subir foto por categoría»**. Las
categorías admisibles de una tarea viven en la columna `cleaning_checklist_templates.required_photos`
(JSONB), cuyas entradas son `RequiredPhotoSpec` — `photo_type`, `label`, `required`.

Esa columna se publica en **exactamente dos esquemas** del contrato, `ChecklistTemplateResponse` y
`CreateChecklistTemplateRequest`, y en ninguna otra ruta. Medido sobre `backend/openapi.json` el
2026-08-23, no inferido. Las dos rutas que los sirven son:

- `GET /api/v1/cleaning-checklist-templates` → `READ_CLEANING_TEMPLATES`
- `POST /api/v1/cleaning-checklist-templates` → `MANAGE_CLEANING_TEMPLATES`

`UserRole.CLEANER` es, en `backend/app/auth/domain/policy.py`, `_SELF_SERVICE | _CLEANING_EXECUTE`:
`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`, `READ_OWN_NOTIFICATIONS`, `READ_CLEANING_TASKS`,
`EXECUTE_CLEANING_TASKS`. **Ninguno de los dos permisos de plantilla está ahí**, y el bundle
`_CLEANING_TEMPLATE_MANAGE` va al owner y al manager por razones propias que esto no reabre (R1.1
de `cleaning`: la plantilla es el estándar al que limpia el tenant, y `checklist_template_id` es
`NOT NULL`, así que quien la administra sostiene el alta automática del checkout).

Y `GET /api/v1/cleaning-tasks/{task_id}/checklist` —que sí alcanza, con `READ_CLEANING_TASKS`—
devuelve un `ChecklistResponse` cuyo `data` es `ChecklistItemStateResponse[]`: `item_id`, `label`,
`required`, `completed`, `completed_at`, `completed_by`. **Los ítems del checklist, no los tipos de
foto.** La simetría que uno esperaría no existe: los ítems llevan su `label` y su `required` a la
limpiadora; las fotos no.

## Lo que la limpiadora sí puede hacer hoy, y por qué no basta

| Puede | Ruta | Con qué |
|---|---|---|
| Subir una foto de un tipo | `POST /cleaning-tasks/{id}/photos` | `EXECUTE_CLEANING_TASKS` |
| Listar las que ya subió, con su `photo_type` | `GET /cleaning-tasks/{id}/photos` | `READ_CLEANING_TASKS` |
| Enumerar los tipos que admite la tarea | — | **nada** |
| Saber cuáles son `required: true` | — | **nada** |
| Leer la etiqueta legible de un tipo | — | **nada** |

La subida contesta `404` cuando el `photo_type` no lo declara la plantilla (`specs/cleaning.md`,
§Fotos de la limpieza), así que sin enumeración la app tendría que adivinar identificadores contra
un `404`. La única vía de descubrimiento que queda es **fallar el cierre**: `POST /complete`
responde `409` enumerando de forma estable los `photo_type` requeridos que faltan. Es decir, la
limpiadora aprendería lo que le piden sólo después de intentar cerrar sin ello — que es
exactamente lo contrario de un botón por categoría.

## Lo que hay que decidir, y no es cosmético

1. **Dónde vive.** Tres formas plausibles, y la elección es de contrato publicado:
   - ensanchar `ChecklistResponse` con un segundo array (`photos` junto a `data`), que junta en una
     petición las dos mitades de la evidencia que el cierre exige;
   - una ruta hermana (`GET /cleaning-tasks/{task_id}/photo-requirements`), que deja
     `/checklist` intacto y hace explícito el recurso;
   - meterlo en `GET /cleaning-tasks/{task_id}/context`, que hoy tiene un `SHALL` fuerte en
     `specs/cleaner-task-context.md` — *«THE SYSTEM SHALL devolver **once campos y solo once**»* —
     así que esta opción **contradice una spec viva** y exigiría enmendarla, no sólo ampliarla.
     Quien la elija tiene que decirlo.
2. **Si el cuerpo dice qué está ya cubierto.** El cliente puede cruzar los tipos declarados contra
   los `photo_type` de `GET /photos`, así que la cobertura es derivable. Pero la regla que gobierna
   el cierre es del servidor —«al menos una por cada tipo `required: true`», verificada dentro de
   `CleaningTask.complete()` con `spec.required_photo_types()`— y dejar que el cliente la reimplemente
   es exactamente cómo dos implementaciones de la misma regla se separan. Decidir a favor de
   incluirla no es gratis: crea un segundo lector de la evidencia junto a
   `CompletionEvidenceGatherer`, y `specs/cleaning.md` es explícita en que las tres cláusulas se
   aplican **en `complete()` y en ningún otro sitio**. Lo que se pide aquí no es aplicarlas, es
   *mostrarlas*; la spec nueva tiene que dejar esa distinción por escrito o el panel la leerá como
   una violación.
3. **Admisible ≠ obligatorio, y el nombre de la columna miente.** `required_photos` declara los
   tipos que la subida admite **con independencia de su `required`** (`specs/cleaning.md`: *«un tipo
   opcional se puede subir, y lo que `required: true` gobierna es el cierre»*), y
   `value_objects.py:63` ya lo dice de sí misma: *«The column's name says `required_photos` while
   the entries in it may perfectly well be…»*. El contrato nuevo no debe heredar esa ambigüedad:
   dos conceptos, dos nombres.
4. **Quién más lo lee.** `READ_CLEANING_TASKS` lo tienen también owner y manager, así que la
   proyección la alcanzan los tres roles. No hay decisión de audiencia que tomar —nada de esto es
   sensible: son etiquetas de una plantilla que el propio tenant escribió— pero el acotamiento por
   `restrict_to_cleaner_id` que ya hace `_load_task` **se hereda y no se amplía**, igual que en
   `cleaner-task-context`.

## Lo que NO decide

- **No decide proveedor, esquema de claves, firma ni tope de tamaño de las fotos.** Eso lo cerraron
  `cleaning-photos-storage` y `object-storage-provisioning`, y la ruta de subida ya existe entera.
- **No toca las tres cláusulas del cierre** ni su orden, ni la enumeración estable del `409`.
- **No concede a `CLEANER` ningún permiso de plantilla.** La alternativa barata —darle
  `READ_CLEANING_TEMPLATES`— le abriría el catálogo de plantillas del tenant entero para resolver
  tres campos de la suya; es la misma alternativa que `cleaner-task-context` descartó con
  `READ_PROPERTIES`, y por el mismo motivo.

## Quién espera

`cleaner-app` (`[FE]`, la app de la limpiadora) declara `needs:` sobre esto desde el 2026-08-23.
Es su último bloqueo conocido: el resto de PRD §11 —lista de tareas propias, dirección y ventana de
trabajo, aceptar/rechazar/iniciar, checklist ítem a ítem, reportar incidencia, finalizar— ya es
alcanzable con los dos permisos que el rol tiene. Censo completo en
[`cleaner-app.md`](cleaner-app.md).
