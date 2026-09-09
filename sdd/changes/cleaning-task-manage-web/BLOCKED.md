# BLOCKED — cleaning-task-manage-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Techo de 100 propiedades en el catálogo compartido

- **phase**: review
- **type**: deferred
- **what & why**: sdd-review-tenancy (info): http-cleaning-source.ts:38 fija CATALOG_PER_PAGE = 100 y ese catálogo alimenta el panel de creación (D9), la barra de filtros y la identidad de fila. Un tenant con más de 100 viviendas no puede crear ni filtrar limpiezas para las que quedan fuera. La restricción es preexistente — este change la reutiliza, no la introduce — pero ninguna spec la declara. Documentar el techo en la sección de spec que D9 referencia, o paginar el catálogo, es trabajo aparte.
- **exact resume command**: /sdd:new cleaning-property-catalog-pagination

## aria-live extra en el contador de caracteres del diálogo de cancelación

- **phase**: review
- **type**: deferred
- **what & why**: sdd-qa (info): cancel-cleaning-task-dialog.tsx:204 añade un span aria-live=polite para el contador de caracteres restantes, replicado del diálogo del dashboard. Las aserciones de región única siguen verdes porque consultan role=status y el span no lo tiene, y solo anuncia una ayuda de formulario, no el resultado de una operación; pero una lectura estricta de D4 ('no es una segunda región aria-live=polite') lo señalaría. Alternativa: texto plano y anuncio solo al cruzar el umbral de 0.
- **exact resume command**: editar cancel-cleaning-task-dialog.tsx:204 si se adopta la lectura estricta de D4
