# Tasks: dashboard-auto-refresh

## 1. Dashboard cards polling <!-- hard --> <!-- panel: PASS 2026-09-15 receipt:a2f58c39 -->

- [x] 1.1 `frontend/features/dashboard/hooks/use-dashboard-data.ts`: definir la constante del
  intervalo MVP como 30.000 ms y configurar `refetchInterval` únicamente en `useDashboardCards`,
  manteniendo `dashboardKeys.cards(tenantId, locale)` y `retryPolicy` sin cambios [R1, R3]
- [x] 1.2 `frontend/features/dashboard/hooks/use-dashboard-data.test.tsx` (nuevo, junto al hook):
  cubrir con `QueryClientProvider`, reloj controlado y data source aislado que la query ejecuta el
  polling nominal de 30 s, usa la identidad tenant/locale en la clave y no mezcla resultados al
  cambiar de tenant [R1, R3]
- [x] 1.3 En el mismo test focal: verificar la opción determinista
  `refetchIntervalInBackground: false` y que no se introduce ningún refetch adicional por focus;
  al reactivar la pestaña solo debe reanudarse el intervalo normal de TanStack Query [R4, R5]

## 2. Continuidad de la vista durante refetch <!-- panel: PASS 2026-09-16 receipt:3173e79d -->

- [x] 2.1 `frontend/features/dashboard/components/dashboard-view.test.tsx`: ampliar la cobertura
  de `DashboardView` para una respuesta previa con refetch en curso, comprobando que las cards
  siguen visibles y no reaparece el skeleton de primera carga [R2, R5]
- [x] 2.2 En el mismo test de vista: cubrir un error posterior al primer éxito, comprobando que
  las últimas cards permanecen visibles y que no se sustituye la vista por el error inicial [R2,
  R5]
- [x] 2.3 `frontend/features/dashboard/components/dashboard-view.tsx`: conservar el renderizado
  existente basado en `isPending`; tocarlo solo si las pruebas demuestran que los datos previos no
  se conservan durante background refetch, sin alterar responsive ni accesibilidad [R2, R5]

## 3. Verification

- [x] 3.1 Ejecutar los tests frontend focales del hook y del dashboard: `cd frontend && npm test --
  use-dashboard-data dashboard-view` [R1, R2, R3, R4, R5]
- [ ] 3.2 Ejecutar la suite frontend completa: `cd frontend && npm test` [R5]
- [ ] 3.3 Ejecutar el typecheck frontend: `cd frontend && npm run typecheck` [R5]
- [ ] 3.4 Ejecutar el lint frontend canónico para la superficie afectada: `cd frontend && npm run
  lint -- features/dashboard` [R5]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- `useDashboardCards` limita el polling a 30.000 ms y `refetchIntervalInBackground: false`; detail y timeline no tienen intervalo.
- Los tests usan reloj fake, baseline independiente, visibilidad/focus deterministas y respuestas tenant A/B diferidas para cubrir carreras de identidad.
- `DashboardView` solo muestra el error de cards cuando no hay datos; un error de refetch conserva las cards previas y no reintroduce el skeleton.
- `cd frontend && npm test` (3.2) · 4e858870 · exit 137 (proceso killed tras >8 min; última salida parcial: 5 fallos en archivos no relacionados con dashboard-auto-refresh — features/reviews/components/reviews-view.test.tsx (×4, primer fallo: `opens on Borradores by default`), features/dashboard/components/property-card.test.tsx (×1, `exposes a localized accessible detail link`), features/pricing/components/pricing-pagination.test.tsx (×1, `disables previous on the first page`), features/landing/components/marketing-nav.test.tsx (×1, `renders exactly two items: a /login link and a #features anchor (es)`); ninguno en `features/dashboard/{hooks/use-dashboard-data,components/dashboard-view}`; vitest no llegó al resumen final). result: timeout.
- `cd frontend && npm run typecheck` (3.3) · 4e858870 · exit 137 (`Killed` con EXITCODE=137, sin salida útil más allá del banner de npm; contenedor llegó a 1.789 GiB / 7.75 GiB y 1174% CPU durante la ejecución). result: timeout.
- `cd frontend && npm run lint -- features/dashboard` (3.4) · 4e858870 · exit 137 (`Killed` con EXITCODE=137, sin salida útil más allá del banner de npm; nota: el script `lint` es `eslint .`, así que `-- features/dashboard` lo añade como segundo target y se analiza `.` completo). result: timeout.
