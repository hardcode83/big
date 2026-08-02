# Propuesta: dashboard-property-card-responsive

## Por qué

Las tarjetas de propiedades del dashboard operativo ya muestran la información necesaria para REDES11 y PAJARITOS8, pero su presentación actual concentra demasiado peso en filas de etiqueta/valor y pierde jerarquía en tablet y móvil. Esto dificulta que una propietaria o manager identifique en menos de 10 segundos el estado de una vivienda, las incidencias abiertas y quién tiene la próxima acción.

Este cambio desarrolla la entrada `[FE] dashboard-property-card-responsive` de `sdd/roadmap.md` y aplica el principio de producto de lectura operativa en menos de 10 segundos, sin ampliar la integración mock existente ni alterar los contratos de datos.

## Qué cambia

Se reorganiza visualmente `PropertyCard` y su presentación en el grid del dashboard para establecer una jerarquía clara entre identidad/estado, reserva y huésped, operación de limpieza/incidencias, próxima acción y último evento. La composición será mobile-first y se adaptará a desktop, tablet y móvil, conservando los datos visibles, los colores operacionales, ES/EN y el enlace al detalle. No se añaden capacidades de negocio ni se modifica la fuente de datos.

## Requisitos

### R1 — Identidad y estado prioritarios

**Como** operador, **quiero** reconocer inmediatamente la propiedad y su estado operacional, **para** saber qué vivienda requiere atención.

Criterios de aceptación:

1. WHEN una card se renderiza, THE SYSTEM SHALL mostrar el código o nombre de la propiedad y el estado operacional en una cabecera visualmente prioritaria.
2. WHEN el estado operacional se renderiza, THE SYSTEM SHALL conservar exactamente el grupo de color existente para ese estado y su etiqueta localizada.
3. THE SYSTEM SHALL obtener identidad y estado del `PropertyDashboardCard` sin recalcular estados, colores ni reglas de negocio en el componente.
4. WHEN una card se renderiza, THE SYSTEM SHALL presentar el estado operacional, las incidencias y la próxima acción en el primer nivel de contenido visible, de forma que puedan identificarse mediante una sola lectura sin interacción adicional.
5. THE SYSTEM SHALL respetar este orden de prioridad visual: estado operacional; incidencias; próxima acción; reserva y huésped; limpieza; último evento.

### R2 — Reserva y operación legibles

**Como** operador, **quiero** distinguir la información de reserva y operación sin una tabla comprimida, **para** entender rápidamente el contexto de la estancia y la limpieza.

Criterios de aceptación:

1. WHEN existe una reserva actual o próxima, THE SYSTEM SHALL mantener visibles la referencia, huésped, check-in y check-out, agrupados como información primaria y legibles sin depender de una única fila horizontal.
2. WHEN no existe una reserva, THE SYSTEM SHALL conservar los estados localizados de ausencia de reserva y huésped sin romper la composición de la card.
3. WHEN la card muestra limpieza, THE SYSTEM SHALL mantener visible su estado y presentarlo como información operativa diferenciada de los datos de reserva.

### R3 — Incidencias y próxima acción destacadas

**Como** operador, **quiero** ver las incidencias y la próxima acción con su responsable, **para** saber qué riesgo existe y qué debe ocurrir después.

Criterios de aceptación:

1. WHEN una card tiene incidencias abiertas, THE SYSTEM SHALL mostrar su cantidad en una región visual claramente identificable y no subordinada a una lista de campos genérica.
2. WHEN existe una próxima acción, THE SYSTEM SHALL darle mayor énfasis visual que la información secundaria y SHALL mostrar su responsable cuando el DTO lo proporcione.
3. WHEN no existe una próxima acción, THE SYSTEM SHALL conservar el comportamiento actual de no inventar una acción ni modificar el DTO.

### R4 — Responsive y acceso al detalle

**Como** operador que usa desktop, tablet o móvil, **quiero** que cada card se adapte al ancho disponible, **para** leerla y activar el detalle sin desplazamiento horizontal ni saltos excesivos.

Criterios de aceptación:

1. WHEN el viewport cambia entre breakpoints de desktop, tablet y móvil, THE SYSTEM SHALL reflowar la card y el grid sin overflow horizontal y sin convertir la card en una tabla comprimida.
2. WHEN el contenido de una card es largo, THE SYSTEM SHALL preservar una jerarquía estable, wrapping/truncado accesible y separación suficiente entre regiones sin ocultar los campos requeridos.
3. WHEN un usuario selecciona el enlace de detalle, THE SYSTEM SHALL conservar la navegación al identificador actual de la propiedad y un objetivo accionable en todos los breakpoints.
4. WHEN un usuario navega por la card mediante teclado, THE SYSTEM SHALL conservar la navegación operable, el foco visible, los nombres accesibles de los elementos interactivos y el contraste y la semántica existentes, sin requerir una auditoría WCAG completa.
5. WHEN las cards contienen cantidades diferentes de contenido, THE SYSTEM SHALL mantener una composición consistente del grid sin alterar significativamente la jerarquía visual definida para cada card.

### R5 — Compatibilidad del contrato y calidad

**Como** equipo de producto, **quiero** que el ajuste sea únicamente de presentación, **para** no introducir regresiones en datos, localización ni comportamiento existente.

Criterios de aceptación:

1. WHEN se renderiza cualquier texto visible de la card, THE SYSTEM SHALL resolverlo mediante las claves existentes o nuevas presentes en las traducciones ES y EN, sin strings hardcodeadas.
2. THE SYSTEM SHALL conservar `PropertyDashboardCard`, `DashboardDataSource`, `MockDashboardSource` y sus fixtures sin cambios de contrato ni conexión al backend.
3. THE SYSTEM SHALL dejar intactos la Timeline, la lógica de negocio, los estados operacionales y los mocks del dashboard.
4. WHEN se verifica el frontend, THE SYSTEM SHALL pasar lint, typecheck, tests y build de producción sin backend en ejecución.

## Fuera de alcance

- Backend, API, autenticación o conexión a un proveedor real.
- Cambios en contratos DTO, `DashboardDataSource`, `MockDashboardSource` o sus fixtures.
- Nuevas funcionalidades o componentes de negocio.
- Cambios en Timeline, estados operacionales, lógica de negocio o reglas de cálculo.
- Cambios en la paleta de colores operacional o en la cobertura i18n ES/EN.

## Especificaciones afectadas

- `sdd/specs/dashboard-web-frontend.md` — actualizar la sección de property cards para documentar la jerarquía visual y el comportamiento responsive al archivar.
