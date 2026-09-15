# BLOCKED — staff-messaging-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## R4.3 excepciona el 404 (tarea/incidencia ya no disponible) de 'conservar el texto escrito'

- **phase**: run
- **type**: assumed
- **what & why**: El panel QA de la sección 2 (run) encontró que un 404 llegado tras empezar a escribir descarta el compositor y su borrador sin aviso, lo cual contradice la letra literal de R4.3. Pero es la MISMA convención que YA aplican las otras cuatro lecturas en paralelo de la pantalla (task/context/checklist/photoRequirements/photos): cualquier 404 de ellas ya sustituye toda la pantalla por un EmptyState 'tarea no disponible', descartando cualquier estado local (incluido el formulario de CleanerIncidentReportPanel). El implementador de la sección 2 ya documentó esta decisión en tasks.md Implementation Notes y en sdd/specs/cleaner-app.md R9 antes de que el panel corriera. Alternativa rechazada: preservar/mostrar el borrador tras el 404 — no tiene destino al que enviarse, la tarea ya no existe para este usuario, y rompería la consistencia con las otras cuatro lecturas. Se amienda R4.3 del proposal para excepcionar explícitamente el 404, en vez de tocar el código para que diverja del resto de la pantalla.
- **exact resume command**: /sdd:run staff-messaging-web — revisar la excepción de R4.3 en el PR; si se prefiere preservar el borrador, reabrir con un patch específico.
