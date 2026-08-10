# App version provenance

The workspace footer shows the public `app_version` from the existing build identity. An
authenticated provenance panel can additionally show the private repository URL, pull request,
full commit SHA, and Actions run, but only as one complete block.

The deployment workflow derives that identity in CI from `GITHUB_SERVER_URL`,
`GITHUB_REPOSITORY`, `GITHUB_SHA`, the commit message, and `GITHUB_RUN_ID`. It writes the
`APP_VERSION` and the `APP_PROVENANCE_*` values to the private deployment `.env` and injects
them only into FastAPI. `APP_VERSION` is exactly the same output used as
`NEXT_PUBLIC_APP_VERSION`; there is no second build-version source.
The backend validates all four values atomically. If one is absent or malformed, provenance is
unknown and no private value or link is returned. `app_version` remains available from that
shared build identity, including when the private provenance block is unknown.

`TENANT_OWNER` and `PROPERTY_MANAGER` may read the protected endpoint. `CLEANER`, `TECHNICIAN`,
and anonymous callers are denied by backend RBAC. The frontend request is made only when an
authenticated user opens the workspace panel; the bearer is held in memory and private values
are never part of `NEXT_PUBLIC_*`, `PublicRuntimeConfig`, root layout props, anonymous HTML,
static assets, JavaScript bundles, `/login`, or `/guest/[token]`.

## Operación y rollback

`unknown`/`unavailable` significa que el bloque privado atómico no está disponible: falta un
campo, un valor no cumple el formato o el despliegue se hizo desde un commit sin PR soportado.
No debe interpretarse como que el `appVersion` público sea inválido; esa identidad se muestra de
forma independiente. El panel no fabrica enlaces parciales.

Para investigar un despliegue, el operador con `TENANT_OWNER` o `PROPERTY_MANAGER` abre el panel
del workspace y compara PR, SHA completo y run de Actions con el artefacto desplegado. Si el panel
está desconocido, se conserva la versión pública y se revisan los logs/configuración privada del
deploy y el subject del commit; no se consulta GitHub desde runtime ni se copia metadata privada
al frontend.

Para un rollback, selecciona la imagen/commit conocido en el procedimiento de deploy y vuelve a
desplegarlo con el flujo de CD. Después comprueba que la identidad pública y, si existe, el bloque
privado corresponden al mismo artefacto. Un rollback cuyo commit no tenga un PR soportado puede
mostrar `unknown`; esto no impide el rollback ni autoriza a inferir un número de issue como PR.

La procedencia privada solo llega al backend a través de `APP_PROVENANCE_REPOSITORY_URL`,
`APP_PROVENANCE_PULL_REQUEST_NUMBER`, `APP_PROVENANCE_COMMIT_SHA` y
`APP_PROVENANCE_ACTIONS_RUN_ID`. El backend exige la unidad completa y el RBAC limita el endpoint
a `TENANT_OWNER` y `PROPERTY_MANAGER`. No se usan secretos ni tokens de GitHub.

Checks:

```bash
make check-version-parity
bash .github/scripts/extract-pr.sh --self-test
make openapi
cd frontend && npm run api:check
npm test -- --run features/provenance
npm run build
npm run test:public-artifacts
```
