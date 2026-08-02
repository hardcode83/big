# Diseño: dashboard-property-card-responsive

## Contexto

`frontend/features/dashboard/components/property-card.tsx` es actualmente un componente presentacional que recibe `PropertyDashboardCard`, traduce las etiquetas del namespace `dashboard` y muestra casi todos los campos mediante filas etiqueta/valor. La cabecera ya combina el código de propiedad con el `Badge` del estado y reutiliza `stateColorGroup`/`STATE_BADGE_CLASS`, mientras que el enlace al detalle conserva la navegación a `/properties/[propertyId]`.

`frontend/features/dashboard/components/dashboard-view.tsx` compone las cards en un grid mobile-first (`grid-cols-1 sm:grid-cols-2 xl:grid-cols-3`). Las pruebas existentes en `property-card.test.tsx` cubren campos del DTO, fallback ES, copy EN y axe; `dashboard-view.test.tsx` cubre los estados de carga/error/vacío y el renderizado del grid.

El cambio es exclusivamente de presentación: no altera `PropertyDashboardCard`, `DashboardDataSource`, `MockDashboardSource`, fixtures, hooks, query keys ni Timeline. Las convenciones de frontend exigen mantener Tailwind mobile-first, i18n ES/EN, colores operacionales y foco visible; `frontend/app/globals.css` ya proporciona el indicador global `:focus-visible` y los tokens de contraste.

## Decisiones

### D1 — Orden semántico único para la jerarquía operativa

**Elegido:** reestructurar el contenido de `PropertyCard` en regiones semánticas cuyo orden DOM coincida con la prioridad visual: cabecera con propiedad/estado, resumen de incidencias, próxima acción y responsable, reserva/huésped con fechas, limpieza y último evento, y enlace al detalle. Usar elementos de agrupación (`header`, `section`/`dl`) y clases de layout, manteniendo el `article` como contenedor de la card.

Esto hace verificable la lectura rápida y mantiene el mismo orden para vista visual, lector de pantalla y teclado; la prioridad no dependerá de `order` CSS divergente. Se reutilizarán los valores del DTO y las claves `dashboard.card.*` existentes.

Rechazado: conservar todas las filas en el orden actual y resolver la jerarquía solo con tipografía — no corrige la competencia entre regiones ni el orden requerido.

### D2 — Énfasis con tokens y colores existentes

**Elegido:** diferenciar las regiones primaria/secundaria con peso tipográfico, espaciado, bordes y fondos neutrales ya disponibles (`bg-card`, `bg-muted`, `text-foreground`, `text-muted-foreground`, `border`, `ring`), reservando `STATE_BADGE_CLASS` para los colores operacionales. La incidencia mostrará siempre su etiqueta y cantidad; cuando haya próxima acción, su bloque tendrá el mayor tratamiento visual entre las acciones informativas y conservará el responsable opcional.

Así se mejora la jerarquía sin crear una nueva semántica de estados ni cambiar la paleta actual. Los textos largos podrán envolver dentro de contenedores con `min-w-0`/wrapping, sin ocultar campos.

Rechazado: introducir colores nuevos para incidencias o acciones — contradiría el criterio de conservar los colores actuales y convertiría una mejora de presentación en una decisión de diseño operacional.

### D3 — Reflow responsive y composición estable del grid

**Elegido:** conservar los breakpoints del grid de `DashboardView` salvo que la implementación demuestre overflow, y hacer que cada `PropertyCard` sea una columna de altura uniforme (`h-full`/flex equivalente) con regiones que puedan crecer de forma controlada. Los pares de fechas y otros datos compactos usarán grids internos que colapsen a una columna en anchos estrechos; se aplicará `min-w-0` y wrapping accesible a valores largos.

El enlace al detalle quedará al final de la columna mediante layout flex, de modo que cards con distinta cantidad de contenido mantengan una base consistente sin alterar el orden de prioridad. No se añadirá scroll horizontal ni truncado que oculte datos requeridos.

Cuando varias `PropertyCard` con distinta cantidad de contenido se muestren simultáneamente en el mismo grid, THE SYSTEM SHALL mantener una alineación visual consistente de la cabecera, las regiones principales y el enlace al detalle, evitando que las diferencias de contenido hagan que unas cards parezcan más largas o desestructuradas que otras.

Rechazado: fijar una altura absoluta o truncar agresivamente todos los valores — produciría pérdida de información y fragilidad ante traducciones ES/EN o nombres largos.

### D4 — Accesibilidad dentro del alcance de la card

**Elegido:** conservar la semántica nativa de `article`, encabezado y enlace; asociar las regiones con etiquetas visibles o `aria-labelledby` solo cuando la estructura lo requiera, sin nombres duplicados. El enlace seguirá siendo el único control interactivo de la card y mantendrá su nombre localizado (`card.openDetail`). Las clases existentes y el foco global de `globals.css` se conservarán; cualquier ajuste de tamaño deberá respetar el objetivo de interacción táctil existente.

La prueba axe actual seguirá siendo obligatoria y se añadirán aserciones de orden, nombre del enlace, foco/semántica estructural cuando sean observables en Testing Library. Esto cubre teclado, foco visible, nombres accesibles, contraste y semántica sin convertir el change en una auditoría WCAG completa.

Rechazado: convertir toda la card en un enlace o añadir controles de acción nuevos — modificaría el comportamiento de navegación y ampliaría el alcance funcional.

### D5 — Traducciones y contrato sin expansión

**Elegido:** reutilizar las claves existentes de `frontend/locales/es/dashboard.json` y `frontend/locales/en/dashboard.json`; solo si el markup necesita una etiqueta visible que no exista, se añadirá la misma clave en ambos locales como parte de la presentación. No se cambiarán tipos, fixtures ni la composición de datos.

Rechazado: derivar etiquetas o estados en el componente desde valores raw del DTO — rompería la frontera de presentación y la regla de i18n.

### D6 — Implementación limitada al árbol de presentación

**Elegido:** limitar la implementación exclusivamente al árbol de render de las cards y del grid, su markup semántico, clases de presentación y organización visual. El change SHALL NOT introducir nuevos hooks, efectos, memoización, consultas, transformaciones de datos ni cambios de estado.

Rechazado: añadir lógica de optimización, derivación o estado local para resolver la jerarquía — ampliaría el alcance y mezclaría presentación con acceso a datos o comportamiento.

## Cambios por área

| Área | Archivos | Cambio |
|---|---|---|
| Card presentacional | `frontend/features/dashboard/components/property-card.tsx` | Reordenar y agrupar el markup según la prioridad operativa; reforzar incidencias/próxima acción; aplicar layout responsive, wrapping y composición consistente; conservar estado, datos, link e i18n. |
| Grid del dashboard | `frontend/features/dashboard/components/dashboard-view.tsx` | Ajustar únicamente clases de composición si hace falta para que las cards ocupen una columna estable en desktop/tablet/móvil; mantener la consulta y los estados de página intactos. |
| Pruebas de card | `frontend/features/dashboard/components/property-card.test.tsx` | Mantener cobertura de DTO, ES/EN y axe; añadir comprobaciones objetivas del orden de regiones, incidencia/próxima acción, fallback y nombre del enlace. |
| Pruebas de grid | `frontend/features/dashboard/components/dashboard-view.test.tsx` | Añadir solo las aserciones estructurales necesarias para la composición responsive/estable, sin simular backend ni introducir lógica de negocio. |
| Traducciones | `frontend/locales/es/dashboard.json`, `frontend/locales/en/dashboard.json` | Sin cambio previsto; solo se tocarán de forma pareada si el markup requiere una etiqueta nueva. |

## Datos e interfaces

Ninguno. No hay cambios de schema, API, DTO, `DashboardDataSource`, `MockDashboardSource`, fixtures, eventos, configuración ni dependencias. `PropertyCard` seguirá consumiendo exactamente `PropertyDashboardCard` y `DashboardView` seguirá usando `useDashboardCards`.

## Cobertura de requisitos

- **R1:** D1 y D2 fijan la cabecera prioritaria, los colores existentes, la ausencia de lógica de negocio y la identificación visible de estado, incidencias y próxima acción.
- **R2:** D1 y D3 separan reserva/huésped, fechas y limpieza en regiones legibles, con fallbacks actuales y reflow en anchos estrechos.
- **R3:** D1 y D2 dan a incidencias y próxima acción regiones explícitas, énfasis y responsable opcional sin inventar datos.
- **R4:** D3 conserva el grid responsive, wrapping, enlace al detalle y composición consistente; D4 mantiene teclado, foco, nombres accesibles, contraste y semántica existentes.
- **R5:** D4, D5 y D6 conservan i18n y accesibilidad, limitan la implementación al render y dejan explícitos el contrato, mocks, Timeline y lógica intactos. La verificación final ejecutará `cd frontend && npm test`, `npm run lint`, `npm run typecheck` y `npm run build`, además de una comprobación visual manual en móvil, tablet y desktop.

## Riesgos y mitigaciones

- **Valores largos o traducciones con distinta longitud:** pueden romper el grid o desplazar el enlace. Mitigación: `min-w-0`, wrapping, grids internos responsive y pruebas con los fixtures existentes en ES/EN.
- **Jerarquía visual divergente entre breakpoints:** estilos específicos pueden hacer que una región secundaria gane peso. Mitigación: mantener el orden DOM único y revisar explícitamente los breakpoints de móvil, tablet y desktop.
- **Regresión de accesibilidad al cambiar markup:** nuevas agrupaciones podrían duplicar nombres o eliminar foco visible. Mitigación: conservar controles nativos, ejecutar axe y añadir aserciones semánticas/keyboard-focus observables.
- **Cambios accidentales en el contrato:** refactors de render podrían intentar transformar DTOs. Mitigación: no modificar `data/`, hooks ni fixtures y mantener las pruebas de campos/fallback existentes.
- **Desalineación entre cards con contenido variable:** una card puede parecer más larga o desplazar su enlace respecto a las demás. Mitigación: revisar la alineación de cabeceras, regiones principales y enlaces en el mismo grid durante la comprobación visual manual.

## Verificación responsive

Además de `cd frontend && npm test`, `npm run lint`, `npm run typecheck` y `npm run build`, el Run incluirá una comprobación visual manual en móvil, tablet y desktop. En cada viewport se verificará la ausencia de overflow horizontal, la estabilidad de la jerarquía visual, la alineación consistente de las cards y la legibilidad del estado operacional, las incidencias y la próxima acción. No se introducirán Playwright, snapshots ni nuevas herramientas automáticas para esta comprobación.

## Preguntas abiertas

Ninguna. El diseño deja como decisión de implementación menor la elección exacta de utilidades Tailwind equivalentes, siempre que cumplan el orden, los tokens y los criterios descritos.
