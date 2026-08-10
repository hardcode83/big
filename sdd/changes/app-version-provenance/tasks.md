# Tasks: app-version-provenance

## 1. Contrato privado y autorización backend

- [x] 1.1 Añadir en `backend/app/core/config.py` las variables `APP_PROVENANCE_*` con validación fail-closed para URL HTTPS de GitHub, PR/run numéricos y SHA completo de 40 hexadecimales; implementar una función/objeto que trate los cuatro campos como unidad atómica y probar presencia completa, ausencia e inputs inválidos [R1, R3]
- [x] 1.2 Añadir `READ_BUILD_PROVENANCE` a `backend/app/auth/domain/policy.py`, concederlo solo a `TENANT_OWNER` y `PROPERTY_MANAGER` y añadir tests de `401`, `403` y acceso permitido siguiendo el test estructural de permisos [R1]
- [x] 1.3 Crear `backend/app/provenance/application/`, `backend/app/provenance/api/` y sus schemas para que el servicio devuelva `app_version` independientemente, pero solo devuelva el bloque privado completo cuando los cuatro campos sean válidos [R1, R3]
- [x] 1.4 Registrar `GET /api/v1/provenance` en `backend/app/main.py` con `require(Permission.READ_BUILD_PROVENANCE)`, respuesta `Cache-Control: private, no-store`, envoltorio OpenAPI explícito y tests de endpoint que demuestren que nunca se devuelven metadatos privados parciales [R1, R3]

## 2. Productor CD y transporte privado al backend

- [x] 2.1 Crear `.github/scripts/extract-pr.sh` con extracción positiva únicamente para `Merge pull request #N ...` y `título (#N)`, salida desconocida para issues/formatos ambiguos y `--self-test` con casos válidos e inválidos [R2]
- [x] 2.2 Extender el job `provenance` de `.github/workflows/deploy-dev.yml` para producir `repository_url`, `pull_request_number`, `commit_sha` y `actions_run_id`; derivar `repository_url` de `GITHUB_SERVER_URL/GITHUB_REPOSITORY`, validarlo y no consultar GitHub en runtime [R1, R2, R3]
- [x] 2.3 Actualizar el paso `deploy` de `.github/workflows/deploy-dev.yml` para escribir las variables `APP_PROVENANCE_*` en el `.env` privado de la VM y comprobar que no se registran sus valores en logs [R1, R3]
- [x] 2.4 Actualizar `docker-compose.deploy.yml` para inyectar `APP_PROVENANCE_*` únicamente en `backend`; verificar que `frontend`, `worker`, `beat`, `migrate` y `cloudflared` no las reciben [R1, R3]
- [x] 2.5 Documentar los nombres sin valores en `.env.example` y actualizar la documentación operativa afectada por el nuevo flujo de procedencia privada [R1, R3]

## 3. Consumidor frontend autenticado

- [x] 3.1 Regenerar `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` para el endpoint de provenance, y añadir el cliente tipado que envía el bearer efímero sin leer `process.env` fuera de `lib/config` [R1, R3]
- [x] 3.2 Crear `frontend/features/provenance/` como isla client-side que solicite `/api/v1/provenance` solo al abrir el panel, mantenga los datos en memoria y trate `provenance: null`/`unavailable` como procedencia desconocida [R1, R3]
- [x] 3.3 Integrar el panel en `frontend/features/shell/components/shell-footer.tsx` y `workspace-shell.tsx` junto al `VersionBadge`, sin añadirlo al `RootLayout`, `PublicShell`, `GuestShell` ni shells de campo [R1]
- [x] 3.4 Construir enlaces únicamente cuando exista el bloque atómico completo; añadir textos ES/EN en `frontend/locales/{es,en}/` y tests de estados de carga, error, desconocido, enlaces y accesibilidad [R1]
- [x] 3.5 Añadir pruebas de seguridad frontend que inspeccionen `PublicRuntimeConfig`, props del root layout, HTML de `/login` y `/guest/[token]`, assets y bundles para demostrar que no contienen URL privada, PR, SHA completo ni run ID [R1, R3]

## 4. Paridad y congruencia CI

- [x] 4.1 Crear `scripts/check-version-parity.py` con `tomllib`/`json`, errores por archivo y código distinto de cero cuando `VERSION`, `backend/pyproject.toml` o `frontend/package.json` falten, estén vacíos o diverjan; cubrir los casos en tests del script [R4]
- [x] 4.2 Añadir `check-version-parity` al `Makefile` como target host-side documentado y sin depender de contenedores [R4]
- [x] 4.3 Añadir a `.github/workflows/frontend-tests.yml` una señal separada para `make check-version-parity` y una verificación explícita de congruencia productor/consumidor de provenance, incluyendo el rechazo de cualquier campo privado en el contrato público [R3, R4]
- [x] 4.4 Mantener el self-test de `.github/scripts/extract-pr.sh` y el gate de paridad ejecutables en una checkout limpia, con mensajes de fallo que identifiquen el contrato roto [R2, R3, R4]

## 5. Documentación y artefactos derivados

- [x] 5.1 Actualizar `README.md` con el target `make check-version-parity`, la ubicación del módulo y la forma de ejecutar sus verificaciones, sin documentar valores privados [R4]
- [x] 5.2 Crear o actualizar `docs/app-version-provenance.md` con el procedimiento operativo para interpretar procedencia desconocida, ausencia de PR y rollback, dejando claro que no hay consulta runtime a GitHub ni secretos/token [R1, R2, R3]
- [x] 5.3 Verificar que las descripciones OpenAPI, los tipos generados y los comentarios de deploy distinguen la identidad pública de `app-version-visibility` del bloque privado atómico [R1, R3]

## 6. Verification

- [x] 6.1 Ejecutar el self-test del extractor: `.github/scripts/extract-pr.sh --self-test` [R2]
- [x] 6.2 Ejecutar el gate de paridad: `make check-version-parity` [R4]
- [x] 6.3 Regenerar y comprobar el contrato API: `make openapi` y `cd frontend && npm run api:check` [R1, R3]
- [x] 6.4 Ejecutar la suite backend del proyecto: `docker compose exec backend uv run pytest` (o `docker compose run --rm backend uv run pytest` con el stack parado) [R1, R2, R3]
- [x] 6.5 Ejecutar tests y calidad frontend: `cd frontend && npm test`, `cd frontend && npm run lint` y `cd frontend && npm run typecheck` [R1, R3, R4]
- [x] 6.6 Ejecutar el build de producción: `cd frontend && npm run build`; inspeccionar los artefactos generados (`.next/`/standalone y bundles estáticos) y verificar que no contienen la URL privada del repositorio, el número de PR, el SHA completo ni el Actions run ID [R1, R3]
- [x] 6.7 Ejecutar tests automatizados de autorización y divulgación que demuestren: `TENANT_OWNER` y `PROPERTY_MANAGER` permitidos; `CLEANER` y `TECHNICIAN` denegados; acceso anónimo denegado; provenance incompleta sin valores privados parciales; y `/login` y `/guest/[token]` sin metadata privada [R1, R3]
- [x] 6.8 Como comprobación complementaria, realizar un smoke manual en un entorno desplegado adecuado: verificar el panel con `TENANT_OWNER`/`PROPERTY_MANAGER` y confirmar estados desconocido/denegado en los demás casos; este smoke no bloquea `/sdd:run` cuando los tests automatizados de 6.7 pasan. No se ejecutó porque no hay un entorno desplegado adecuado disponible en esta sesión [R1, R3]

## 7. Review remediation

- [x] 7.1 Definir la fuente canónica JSON del contrato de provenance y añadir una regresión que compruebe el wiring real de todos los campos, formatos, atomicidad, ausencia pública y transporte solo al backend en workflow/Compose [R3]
- [x] 7.2 Expresar en los schemas Pydantic los constraints públicos de URL GitHub HTTPS, PR/run positivos y SHA completo; regenerar OpenAPI y tipos frontend; añadir pruebas de rechazo y bloque atómico [R3]
- [x] 7.3 Actualizar la documentación de identidad pública frente a provenance privada, endpoint/RBAC/configuración, estados unknown/unavailable, lookup runtime y procedimiento de rollback, sin valores privados [R1, R3, R4]
- [x] 7.4 Verificar la metadata de planificación del roadmap (`needs`, `size`, `kind`) contra el formato soportado, conservarla sin cambios y retirar de `BLOCKED.md` el finding descartado [steering SDD]
- [x] 7.5 Ejecutar las verificaciones dirigidas y completas de esta remediación, incluido `/sdd:doctor`, y retirar `BLOCKED.md` solo si todos los findings pasan revisión [R1, R3, R4]
