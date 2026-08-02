# Design: frontend-dependency-security

## Context

El frontend declara sus dependencias en `frontend/package.json` y fija la resolución reproducible en `frontend/package-lock.json` (lockfile v3). El baseline de 2026-08-02 contiene `next` 16.2.10 como dependencia directa; `postcss` 8.4.31 y `sharp` 0.34.5 llegan por Next; y dos ramas de desarrollo de `brace-expansion` —1.1.16 y 5.0.7— llegan por `minimatch` desde ESLint y `eslint-config-next`. `npm audit` reporta cuatro paquetes afectados y `npm audit --omit=dev` tres, porque `brace-expansion` no forma parte del árbol de producción. La aplicación usa App Router y salida `standalone` (`frontend/next.config.ts`), pero no contiene middleware/proxy, Server Actions, custom server, rewrites ni `next/image`; aun así, Next, PostCSS y Sharp forman parte de la instalación desplegable y deben quedar fuera de sus rangos vulnerables.

Baseline trazable:

| Dependencia | Tipo y ruta | Versión inicial | Rango vulnerable / advisories | Versión final mínima | Motivo |
|---|---|---:|---|---:|---|
| `next` | Directa (`frontend/package.json`) | 16.2.10 | `>=16.0.0 <16.2.11`: GHSA-6gpp-xcg3-4w24, GHSA-m99w-x7hq-7vfj, GHSA-89xv-2m56-2m9x, GHSA-68g3-v927-f742, GHSA-4633-3j49-mh5q, GHSA-4c39-4ccg-62r3, GHSA-p9j2-gv94-2wf4, GHSA-q8wf-6r8g-63ch y GHSA-955p-x3mx-jcvp | 16.2.11 | Primer parche fuera de los nueve rangos directos vulnerables. |
| `postcss` | Transitiva; Next la fija a 8.4.31 (Tailwind/Vite también la consumen) | 8.4.31 | `<=8.5.17`: GHSA-qx2v-qp2m-jg93, GHSA-6g55-p6wh-862q y GHSA-r28c-9q8g-f849 | 8.5.18 | Primera versión que corrige los tres advisories; Next 16.2.11 sigue fijando 8.4.31. |
| `sharp` | Transitiva opcional de Next | 0.34.5 | `<0.35.0`: GHSA-f88m-g3jw-g9cj (libvips: CVE-2026-33327, CVE-2026-33328, CVE-2026-35590 y CVE-2026-35591) | 0.35.0 | Primera versión corregida; Next 16.2.11 mantiene `^0.34.5`. |
| `brace-expansion` | Transitiva de desarrollo: `eslint`/plugins → `minimatch` 3.1.5 | 1.1.16 | `<1.1.17`: GHSA-mh99-v99m-4gvg | 1.1.17 | Primer parche corregido permitido por `minimatch` (`^1.1.7`). |
| `brace-expansion` | Transitiva de desarrollo: `eslint-config-next` → `typescript-eslint` → `minimatch` 10.2.5 | 5.0.7 | `>=4.0.0 <5.0.8`: GHSA-mh99-v99m-4gvg | 5.0.8 | Primer parche corregido permitido por `minimatch` (`^5.0.5`). |

Detalle individual de severidad del baseline (`npm audit --json`, 2026-08-02):

| Paquete | Advisory | Severidad | Rango vulnerable | Ruta y ámbito |
|---|---|---|---|---|
| `next` | GHSA-6gpp-xcg3-4w24 | high | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-m99w-x7hq-7vfj | high | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-89xv-2m56-2m9x | high | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-68g3-v927-f742 | moderate | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-4633-3j49-mh5q | moderate | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-4c39-4ccg-62r3 | moderate | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-p9j2-gv94-2wf4 | high | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-q8wf-6r8g-63ch | moderate | `>=16.0.0 <16.2.11` | Directa; producción |
| `next` | GHSA-955p-x3mx-jcvp | moderate | `>=16.0.0 <16.2.11` | Directa; producción |
| `postcss` | GHSA-qx2v-qp2m-jg93 | moderate | `<8.5.10` | Transitiva de Next; producción |
| `postcss` | GHSA-6g55-p6wh-862q | high | `<=8.5.11` | Transitiva de Next; producción |
| `postcss` | GHSA-r28c-9q8g-f849 | high | `<=8.5.17` | Transitiva de Next; producción |
| `sharp` | GHSA-f88m-g3jw-g9cj | high | `<0.35.0` | Transitiva opcional de Next; producción |
| `brace-expansion` | GHSA-mh99-v99m-4gvg | high | `<1.1.17` | Transitiva de desarrollo: `minimatch` 3.1.5 |
| `brace-expansion` | GHSA-mh99-v99m-4gvg | high | `>=4.0.0 <5.0.8` | Transitiva de desarrollo: `minimatch` 10.2.5 |

Las severidades anteriores son las propiedades `via[].severity` de los informes JSON capturados; la severidad agregada `high` por paquete se conserva únicamente como resumen. `npm audit --omit=dev` confirmó el mismo detalle para `next`, `postcss` y `sharp`; `brace-expansion` queda fuera de producción por ser exclusivamente de desarrollo.

Como evidencia histórica del baseline, todos esos primeros candidatos corregidos aceptaban Node 22: Next 16.2.11 y Sharp 0.35.0 requerían Node `>=20.9.0`, PostCSS 8.5.18 admitía Node `>=14`, y brace-expansion 5.0.8 admitía Node 20 o `>=22`. La implementación volverá a comprobar los engines de las versiones mínimas seleccionadas en ese momento.

### Evidencia de Run — baseline previo (2026-08-02)

Los audits reejecutados antes de modificar el árbol confirmaron el baseline sin advisories nuevos: `npm audit --json` devolvió 4 paquetes afectados, todos con severidad agregada high (`next`, `postcss`, `sharp` y `brace-expansion`), mientras `npm audit --omit=dev --json` devolvió 3 (`next`, `postcss` y `sharp`). Next sigue siendo la única dependencia directa afectada; PostCSS y Sharp son transitivas de producción introducidas por Next, y las dos ramas de brace-expansion son transitivas de desarrollo bajo `minimatch`.

La consulta de los manifests publicados confirmó como primeros candidatos corregidos compatibles con Node 22 los que figuran en la tabla: Next 16.2.11, PostCSS 8.5.18, Sharp 0.35.0 y brace-expansion 1.1.17/5.0.8. La simulación `npm install next@16.2.11 --package-lock-only --dry-run --ignore-scripts --no-audit --no-fund` no modificó `package.json` ni el lockfile. El manifest de Next 16.2.11 continúa fijando PostCSS 8.4.31 y declarando `sharp ^0.34.5`, por lo que actualizar Next no corrige esas dos rutas; ambos overrides siguen siendo necesarios. Los padres `minimatch` declaran `^1.1.7` y `^5.0.5`, rangos que ya admiten respectivamente las primeras versiones corregidas de brace-expansion, pero el lockfile inicial conserva 1.1.16 y 5.0.7.

### Evidencia de Run — checkpoint de Next.js (2026-08-02)

Next se actualizó de 16.2.10 a 16.2.11 porque es el primer parche compatible con Node 22 fuera de los nueve rangos directos vulnerables. La regeneración del lockfile modificó únicamente Next, `@next/env` y los binarios SWC de la misma versión; `eslint-config-next` y las demás dependencias permanecieron intactas.

Desde una copia limpia en `node:22-slim`, `npm ci`, los 250 tests de los 46 archivos, lint, typecheck y build finalizaron correctamente. El build conservó las 20 rutas de la aplicación, incluida `/dashboard`. La imagen de producción definida por `frontend/devops/Dockerfile` construyó la salida standalone, arrancó con Next 16.2.11 y devolvió HTTP 200 para `/dashboard` (33.165 bytes), sin evidencia de cambios observables en SSR, routing, build o renderizado ni necesidad de rollback.

### Evidencia de Run — checkpoint de PostCSS (2026-08-02)

Tras actualizar Next, su ruta continuaba resolviendo PostCSS 8.4.31. Se añadió el override acotado Next → PostCSS 8.5.18, primera versión corregida compatible, para eliminar los tres advisories sin convertir PostCSS en dependencia directa. En `node:22-slim`, `npm ci`, los 250 tests, lint, typecheck y build finalizaron correctamente. `npm ls postcss` documentó `next@16.2.11 → postcss@8.5.18`; las ramas independientes y ya seguras de Tailwind y Vite permanecieron en 8.5.19. No fue necesario aplicar rollback.

### Evidencia de Run — checkpoint de Sharp (2026-08-02)

Next 16.2.11 continuaba resolviendo Sharp 0.34.5. Se añadió el override acotado Next → Sharp 0.35.0, primera versión corregida compatible con Node 22; el lockfile refleja el cambio esperado de sus binarios nativos y de libvips 1.2.4 a 1.3.0. Sharp permanece como dependencia transitiva opcional de Next. En `node:22-slim`, `npm ci`, los 250 tests, lint, typecheck y build finalizaron correctamente, y `npm ls sharp` documentó `next@16.2.11 → sharp@0.35.0`. La imagen de `frontend/devops/Dockerfile` construyó la salida standalone, arrancó y devolvió HTTP 200 para `/dashboard` (33.165 bytes), sin regresión ni rollback.

### Evidencia de Run — checkpoint de brace-expansion (2026-08-02)

Las ramas de `minimatch` 3.1.5 y 10.2.5 conservaban respectivamente brace-expansion 1.1.16 y 5.0.7 tras actualizar Next. Los overrides acotados del checkpoint regeneraron el lockfile con 1.1.17 y 5.0.8, las primeras versiones corregidas admitidas por los rangos `^1.1.7` y `^5.0.5`. En `node:22-slim`, `npm ci` informó cero vulnerabilidades; los 250 tests, lint, typecheck y build finalizaron correctamente, y `npm ls minimatch brace-expansion` confirmó ambas rutas seguras.

De acuerdo con D3, los dos overrides de brace-expansion se retiraron antes de la verificación final: al regenerar el árbol sin ellos, el lockfile conservó naturalmente 1.1.17 y 5.0.8 porque ambos padres ya admiten esas resoluciones. Los overrides de PostCSS y Sharp se mantienen, ya que Next 16.2.11 continúa declarando respectivamente 8.4.31 y `^0.34.5` y el árbol volvería a versiones vulnerables sin esas excepciones.

### Evidencia de Run — verificación final (2026-08-02)

La verificación final partió de una copia limpia en `node:22-slim`. `npm ci` instaló 505 paquetes sin alterar el lockfile; los 250 tests de 46 archivos, lint, typecheck y build terminaron en verde, y el build conservó las 20 rutas. `npm ls next postcss sharp brace-expansion` documentó las resoluciones efectivas: Next 16.2.11; Next → PostCSS 8.5.18; Next → Sharp 0.35.0; `minimatch` 3.1.5 → brace-expansion 1.1.17; y `minimatch` 10.2.5 → brace-expansion 5.0.8. Las ramas independientes de PostCSS usadas por Tailwind y Vite resolvieron 8.5.19.

Tanto `npm audit --json` como `npm audit --omit=dev --json` terminaron con código 0 y cero vulnerabilidades en todos los niveles; no aparecieron advisories nuevos ni exposiciones residuales que justificar. La imagen final definida por `frontend/devops/Dockerfile` completó `npm ci` y build con Node 22, produjo la salida standalone, arrancó con Next 16.2.11 y devolvió HTTP 200 para `/dashboard` (33.165 bytes). El diff de implementación no modifica código funcional, componentes del dashboard, tests, mocks, fixtures, contratos API ni workflows.

## Decisions

### D1 — Actualizar únicamente la dependencia directa vulnerable

**Chosen:** elevar el rango declarado de `next` desde `^16.2.10` hasta la primera versión corregida compatible que, en el momento de implementar, quede fuera de todos los rangos vulnerables directos, conserve el major y admita Node 22; el lockfile fijará esa resolución. El baseline identificó 16.2.11 como el primer candidato conocido, pero el número no es un requisito rígido si una revisión posterior de seguridad desplaza el umbral. `eslint-config-next` permanecerá en 16.2.10 salvo que una verificación objetiva demuestre incompatibilidad: no está afectado y alinearlo por estética violaría el criterio de actualización mínima. Cubre R1 y R2.

Rejected: actualizar Next automáticamente a la última versión disponible — añade cambios no necesarios para salir del rango vulnerable.

Rejected: actualizar también `eslint-config-next` — no remedia ninguno de los cuatro paquetes afectados.

### D2 — Corregir las transitivas con overrides mínimos y acotados

**Chosen:** declarar en `frontend/package.json` overrides acotados a las rutas cuyos padres todavía resuelvan versiones vulnerables. Para cada ruta se elegirá la primera versión corregida compatible admitida por el padre correspondiente y por Node 22:

- ruta Next → PostCSS: primera versión fuera de todos los rangos vulnerables de PostCSS que Next pueda resolver mediante override;
- ruta Next → Sharp: primera versión fuera del rango vulnerable de Sharp compatible con Next y Node 22;
- cada ruta `minimatch` → `brace-expansion`: primera versión corregida que satisfaga el rango admitido por esa rama del padre.

La simulación inicial de `npm audit fix --dry-run` confirmó que actualizar Next por sí solo, incluso al parche disponible durante el diseño, conservaba PostCSS 8.4.31 y Sharp 0.34.5; por tanto los overrides eran necesarios en el baseline. Los dos `minimatch` ya admitían las primeras versiones corregidas. Antes de escribir cada override se volverán a consultar el audit y el manifest del padre: la tabla superior conserva los umbrales conocidos al diseñar, pero la implementación no congelará una versión que haya dejado de ser la mínima segura compatible. Cubre R1, R2 y R3.

Rejected: añadir `postcss`, `sharp` o `brace-expansion` como dependencias directas — la aplicación no las importa y falsearía la propiedad del árbol.

Rejected: un override global por nombre de paquete — ampliaría el radio a rutas no afectadas y ocultaría qué padre obliga la corrección.

Rejected: `npm audit fix --force` — puede introducir saltos no controlados y está prohibido por R2.

### D3 — Mantener los overrides como remediación temporal

**Chosen:** tratar cada override como una excepción temporal, no como la resolución normal permanente. En futuras actualizaciones de Next.js, `minimatch` o cualquier otro padre afectado, se generará y examinará primero el árbol sin el override correspondiente. Si el padre ya resuelve de forma natural una versión segura compatible y `npm audit` permanece limpio para esa ruta, el override se eliminará; si aún es necesario, se conservará con su justificación y umbral de seguridad actualizados. Así se vuelve a la resolución ordinaria del ecosistema tan pronto como sea seguro, sin retirar protección antes de tiempo. Cubre R2 y R3.

Rejected: conservar indefinidamente los overrides aunque los padres ya sean seguros — acumula deuda y puede bloquear deduplicación o actualizaciones legítimas.

Rejected: eliminar un override solo porque el padre cambió de versión — el árbol resuelto y el audit, no el número del padre por sí solo, demuestran que la excepción dejó de ser necesaria.

### D4 — Tratar la actualización corregida de Sharp como riesgo material

**Chosen:** tratar el salto desde Sharp 0.34.5 hasta la primera versión corregida compatible como una actualización con riesgo material. La evidencia inicial situaba ese umbral en 0.35.0, que cambiaba los binarios nativos y libvips de 1.2.4 a 1.3.0; la implementación volverá a confirmar el primer candidato seguro y sus cambios. La mitigación es validar instalación y build en `node:22-slim`, comprobar la salida standalone y ejecutar un arranque HTTP de producción. La aplicación no usa `next/image`, por lo que no se modifica ninguna superficie de imagen ni se añade una prueba funcional inventada; el build/arranque confirma que el binding opcional que Next instala es compatible. Cubre R2.4, R2.5, R4 y R5.

Rejected: dejar Sharp vulnerable porque hoy no se usa `next/image` — sigue instalado en producción y `npm audit --omit=dev` lo reporta como corregible.

Rejected: deshabilitar o eliminar Sharp — alteraría la composición esperada por Next y no demuestra una remediación compatible.

### D5 — Aplicar y verificar cada resolución como unidad reversible

**Chosen:** implementar en cuatro checkpoints lógicos: (1) primera versión corregida compatible de Next; (2) override mínimo de PostCSS si sigue siendo necesario; (3) override mínimo de Sharp si sigue siendo necesario; (4) los overrides mínimos de brace-expansion que continúen siendo necesarios. Tras cada checkpoint se regenerará el lockfile mediante npm y se verificará que el diff contiene solo la dependencia objetivo y sus artefactos inevitables. Se registrarán versión inicial, versión final y motivo usando la tabla de este Design como baseline, actualizándola con la resolución real.

Si un checkpoint provoca una regresión demostrable en `npm ci`, tests, lint, typecheck o build, se revertirá solo su cambio en `package.json`, se regenerará `package-lock.json` desde el último checkpoint verde y se añadirá aquí una sección de incidencia con comando, salida resumida, causa y decisión antes de continuar. No se usarán resets destructivos ni se mezclarán rollbacks de dependencias independientes. Cubre R1.4 y R3.5.

Rejected: actualizar todas las dependencias en un único comando — impide atribuir una regresión y revertir solo su causa.

Rejected: editar manualmente `package-lock.json` — rompe la reproducibilidad y el modelo de integridad de npm.

### D6 — Verificación completa bajo Node 22

**Chosen:** capturar antes y después `npm audit` y `npm audit --omit=dev`, y ejecutar la validación final desde una instalación limpia bajo Node 22: `npm ci`, `npm test`, `npm run lint`, `npm run typecheck` y `npm run build`. Tras `npm ci` se ejecutará además `npm ls next postcss sharp brace-expansion` para registrar como evidencia documental las versiones y rutas realmente resueltas; esta inspección no es un gate funcional ni sustituye a `npm audit`. Finalmente se arrancará la salida de producción y se hará un smoke HTTP de `/dashboard` para cubrir conjuntamente SSR, routing y renderizado básico. Los tests existentes de rutas, wiring, Server Components y dashboard aportan la señal funcional; no se modificarán componentes, mocks, fixtures, contratos API ni tests para acomodar un fallo.

El objetivo del audit posterior es cero vulnerabilidades para el baseline analizado, tanto en el árbol completo como con `--omit=dev`. Si el registro publica un advisory nuevo durante la ejecución, se separará del baseline, se analizará con el mismo formato y, si no es corregible dentro del alcance, se documentará como exposición residual según R3. Cubre R2.5, R3, R4 y R5.

Rejected: validar con la versión de Node disponible en el host — no demuestra la compatibilidad contractual con Node 22 usada en CI y en `frontend/devops/Dockerfile`.

Rejected: limitar la verificación a `npm audit` — no detecta regresiones de tipos, build, renderizado ni binarios nativos.

Rejected: añadir un gate permanente de audit al workflow — está fuera de alcance y requiere una decisión separada de política CI.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Manifest de frontend | `frontend/package.json` | Elevar Next a la primera versión corregida compatible y añadir solo los overrides mínimos y acotados de PostCSS, Sharp y brace-expansion que el árbol natural todavía necesite. No cambiar scripts ni otras dependencias. |
| Resolución reproducible | `frontend/package-lock.json` | Regenerar con npm las versiones e integridades resultantes; rechazar churn no atribuible a las cinco resoluciones de la tabla. |
| Evidencia SDD | `sdd/changes/frontend-dependency-security/design.md` | Mantener la matriz inicial/final/motivo y registrar aquí cualquier riesgo, desviación, rollback o vulnerabilidad residual. |
| Código y contratos | `frontend/app/**`, `frontend/features/**`, `frontend/components/**`, `frontend/lib/**`, mocks y `backend/openapi.json` | Sin cambios. Se usan únicamente como superficies de verificación existentes. |
| CI/CD | `.github/workflows/**`, `frontend/devops/Dockerfile` | Sin cambios. Proporcionan Node 22 y el build existente; no se añade un gate de audit. |

## Data & interfaces

No hay cambios de esquema, datos, API, eventos, variables de entorno, rutas, props, estado de UI ni contratos externos. La única interfaz modificada es el contrato de instalación de npm expresado por `frontend/package.json` y `frontend/package-lock.json`; `npm ci` sigue siendo la vía reproducible y Node 22 sigue siendo la versión de ejecución.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| La primera versión corregida compatible de Sharp puede introducir cambios en sus binarios nativos, en la versión de libvips o en la salida standalone. | Verificar los engines y cambios nativos de la versión finalmente seleccionada; ejecutar `npm ci` y build con Node 22; construir la imagen definida por `frontend/devops/Dockerfile`; comprobar la salida standalone; ejecutar el smoke HTTP; aplicar rollback aislado y registrar la incidencia si falla. |
| Un parche de Next altera SSR, routing, build o renderizado observable. | Suite completa, tests de rutas/wiring y smoke HTTP de `/dashboard`; identificar el efecto y detenerse para documentarlo si no puede demostrarse ausencia de regresión. |
| Los overrides ocultan futuras mejoras de los padres. | Scope estrecho y D3: volver a resolver sin cada override al actualizar el padre, comprobar el árbol con `npm ls` y el riesgo con `npm audit`, y retirarlo cuando la resolución natural sea segura. |
| La regeneración del lockfile actualiza paquetes no relacionados. | Checkpoints por dependencia y revisión del diff; descartar y regenerar cualquier churn ajeno. |
| Aparece un advisory nuevo entre baseline e implementación. | Separarlo del baseline, analizar ruta/exposición y corregirlo solo si cabe en el alcance; en otro caso justificarlo documentalmente según R3. |
| Un gate falla y se intenta compensar cambiando producto o tests. | No modificar código funcional, dashboard, mocks, contratos ni tests; rollback exclusivo de la resolución causante. |

## Open questions

Ninguna. Las cuatro vulnerabilidades tienen correcciones mínimas compatibles con Node 22 y las decisiones anteriores no requieren ampliar el alcance funcional.
