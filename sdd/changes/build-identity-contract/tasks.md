# Tasks: build-identity-contract

## 1. Contrato compartido y frontera pública <!-- panel: PASS 2026-08-08 -->

- [x] 1.1 Añadir `frontend/lib/config/build-identity-contract.json` con los patrones y
  literales no sensibles acordados en D1/D3 (`X.Y.Z`, identidad canónica, commit de 7 hex,
  `local` y pareja local vacía), y adaptar `frontend/lib/config/public.ts` para construir sus
  validadores desde ese contrato sin cambiar las formas aceptadas ni la degradación a `""`.
  Mantener fuera del snapshot el SHA completo, PR, `run_id`, `ref` y URL del repositorio. [R2,
  R3]
- [x] 1.2 Actualizar `frontend/lib/config/public.test.tsx` para demostrar que las formas
  legítimas actuales siguen pasando (identidad canónica, base `X.Y.Z` y `local`/vacío) y que
  los valores fuera de forma siguen cayendo a cadena vacía, incluyendo SHA largo, fecha fuera
  de rango, base no `X.Y.Z` y valores de procedencia. [R2, R3]

## 2. Compositor y validador del productor CD <!-- panel: PASS 2026-08-08 -->

- [x] 2.1 Crear `frontend/scripts/build-identity.mjs` como módulo ESM sin dependencias externas,
  con funciones puras para leer/validar la base, componer la identidad canónica desde un SHA y
  un timestamp deterministas, validar la versión final y exigir que el sufijo coincida con
  `commit_short`. Validar timestamp UTC, base `X.Y.Z`, SHA corto de 7 hex y todos los outputs
  finales antes de devolverlos. [R1]
- [x] 2.2 Añadir la interfaz CLI del mismo `frontend/scripts/build-identity.mjs`: leer `VERSION`
  y las variables estándar de Actions, tomar una única instantánea UTC, componer también
  `repo_url`, y escribir `version`, `commit_short`, `built_at` y `repo_url` a
  `$GITHUB_OUTPUT` en una única operación posterior a la validación. Los errores deben terminar
  antes de escribir outputs y nombrar el componente inválido sin exponer procedencia adicional.
  [R1]
- [x] 2.3 Crear `frontend/lib/config/build-identity-contract.test.ts` con casos deterministas
  positivos y negativos contra las funciones puras y la CLI: identidad canónica aceptada,
  pareja versión/commit aceptada, commit de longitud distinta de 7, fecha no canónica, base
  no `X.Y.Z`, fallo sin outputs parciales y pareja local `local`/vacío aceptada por la frontera.
  [R1, R2, R3]

## 3. Integración del workflow, CI y documentación <!-- panel: PASS 2026-08-08 -->

- [x] 3.1 Sustituir en `.github/workflows/deploy-dev.yml` la composición Bash del step
  `provenance` por `node frontend/scripts/build-identity.mjs`, conservar los outputs
  `version`, `commit_short`, `built_at` y `repo_url`, y mantener los build-args/labels de
  `build-backend` y `build-frontend` consumiendo `needs.provenance.outputs.*`. [R1]
- [x] 3.2 Completar `frontend/lib/config/build-identity-contract.test.ts` con la aserción de
  cableado sobre `.github/workflows/deploy-dev.yml`: el workflow delega la composición al
  script y no vuelve a construir `version` o `commit_short` inline; además, verificar los dos
  defaults explícitos de `docker-compose.yml` (`local` y commit vacío) sin levantar el stack.
  [R2, R3]
- [x] 3.3 Actualizar `docs/app-version-visibility.md` y los comentarios de
  `frontend/lib/config/public.ts` para sustituir la advertencia de que no existe comprobación
  automática por el nuevo gate, describir que `frontend-tests` lo ejecuta en Pull Requests y
  conservar las advertencias de divulgación y degradación cerrada. [R2, R3]

## 4. Verificación

- [x] 4.1 Desde `frontend/`, instalar dependencias de forma reproducible con `npm ci` y ejecutar
  la suite completa con `npm test`, incluyendo la prueba de contrato productor-consumidor.
  [R1, R2, R3]
- [x] 4.2 Desde `frontend/`, ejecutar `npm run lint` y `npm run typecheck`; resolver cualquier
  error introducido por el JSON compartido, el módulo ESM o sus tests sin relajar TypeScript
  strict ni la configuración de ESLint. [R1, R2, R3]
- [x] 4.3 Desde `frontend/`, ejecutar `npx vitest run lib/config/build-identity-contract.test.ts`
  con los casos negativos y comprobar que una mutación de la forma producida (SHA, fecha o
  base) hace fallar la validación, mientras `local`/vacío continúa pasando; verificar también
  que no quedan outputs escritos tras un fallo. [R1, R2, R3]
- [x] 4.4 Ejecutar `git diff --check` y revisar el diff final para confirmar que no hay cambios
  en backend, base de datos, API, staging/prod ni en la forma canónica o el límite de
  divulgación; confirmar que las specs vivas quedan para la actualización objetiva durante
  `/sdd:archive`. [R1, R2, R3]
