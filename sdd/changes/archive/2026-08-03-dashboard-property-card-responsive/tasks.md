# Tareas: dashboard-property-card-responsive

## 1. Reorganización presentacional de la Property Card <!-- panel: PASS 2026-08-03 -->

- [x] 1.1 Reestructurar `frontend/features/dashboard/components/property-card.tsx` en regiones semánticas con orden DOM y visual `estado → incidencias → próxima acción → reserva/huésped → limpieza → último evento → detalle`, manteniendo `PropertyDashboardCard`, `stateColorGroup`, los colores actuales, los fallbacks y el enlace existente; limitar el cambio a markup, clases y organización visual, sin hooks, efectos, memoización, consultas, transformaciones de datos ni estado nuevo [R1, R2, R3, R4, R5]
- [x] 1.2 Aplicar en `frontend/features/dashboard/components/property-card.tsx` el énfasis visual definido para estado, incidencias y próxima acción usando tokens/clases existentes, wrapping seguro (`min-w-0` y equivalentes), nombre accesible localizado del enlace y semántica/foco nativos; ampliar `frontend/features/dashboard/components/property-card.test.tsx` para verificar campos, orden de regiones, responsable opcional, fallback sin reserva/acción, navegación al detalle, ES/EN y ausencia de violaciones axe [R1, R2, R3, R4, R5]

## 2. Grid responsive y alineación entre cards <!-- panel: PASS 2026-08-03 -->

- [x] 2.1 Ajustar únicamente las clases de `frontend/features/dashboard/components/dashboard-view.tsx` y, si fuese necesario, las clases de `frontend/features/dashboard/components/property-card.tsx` para mantener el reflow mobile-first sin overflow horizontal, columnas estables, regiones principales alineadas y el enlace al detalle en una posición consistente cuando las cards tengan contenido variable; no alterar query, estados de carga/error/vacío ni composición de datos [R2, R4, R5]
- [x] 2.2 Añadir en `frontend/features/dashboard/components/dashboard-view.test.tsx` las aserciones estructurales necesarias para verificar el grid y la composición estable de varias cards, sin snapshots, Playwright, nuevos hooks ni nuevas herramientas automáticas [R4, R5]

## 3. Traducciones y contrato

- [x] 3.1 Verificar que `frontend/locales/es/dashboard.json` y `frontend/locales/en/dashboard.json` cubren todas las etiquetas visibles de la nueva organización; reutilizar las claves existentes y, solo si aparece una etiqueta nueva imprescindible, añadirla de forma pareada sin modificar `PropertyDashboardCard`, `DashboardDataSource`, `MockDashboardSource`, fixtures, hooks, query keys ni Timeline [R5]

## 4. Verificación

- [x] 4.1 Ejecutar la suite del frontend desde `frontend`: `npm test` [R5]
- [x] 4.2 Ejecutar lint desde `frontend`: `npm run lint` [R5]
- [x] 4.3 Ejecutar typecheck desde `frontend`: `npm run typecheck` [R5]
- [x] 4.4 Ejecutar build de producción desde `frontend`: `npm run build` [R5]
- [x] 4.5 Realizar una comprobación visual manual en móvil, tablet y desktop, tanto en español como en inglés, con varias cards de distinto contenido, verificando ausencia de overflow horizontal, wrapping correcto para textos largos, estabilidad de la jerarquía en ambos idiomas, alineación consistente de cabecera/regiones/enlace y legibilidad de estado, incidencias y próxima acción. Comprobar también la navegación mediante teclado, el foco visible del enlace al detalle y su nombre accesible localizado; no convertirlo en una auditoría WCAG completa ni usar Playwright, snapshots o herramientas automáticas nuevas [R1, R2, R3, R4]
