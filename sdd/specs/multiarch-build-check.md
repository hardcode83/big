# Verificación de build multi-arquitectura

## Purpose

Esta capacidad verifica en GitHub Actions, en cada Pull Request que toque los Dockerfiles o
los manifiestos de dependencias, que las imágenes de producción de backend y frontend
construyen para **linux/arm64** (la instancia Ampere A1 del entorno dev, ADR 0001) además de
**linux/amd64**, sin publicar ninguna imagen a un registry. Existe para que un cambio de
dependencias o de Dockerfile que rompa el build de `arm64` se detecte en el Pull Request, no en
el siguiente `deploy-dev` real.

Es una capacidad separada de `app-deploy-dev`: verifica que el build funciona, no publica ni
despliega.

## Requirements

### Disparadores y alcance

- WHEN se abre o actualiza un Pull Request que toca `backend/devops/Dockerfile`,
  `backend/pyproject.toml`, `backend/uv.lock`, `frontend/devops/Dockerfile`,
  `frontend/package.json`, `frontend/package-lock.json` o el propio workflow, THE SYSTEM SHALL
  ejecutar `multiarch-build-check`.
- WHEN una persona inicia una ejecución manual, THE SYSTEM SHALL admitir `workflow_dispatch`.
- THE SYSTEM SHALL usar `paths:` en `on:` para este workflow, a diferencia de los demás
  workflows del repositorio (`specs/backend-ci.md` prohíbe `paths:` en `on:` para checks que
  deben reportar siempre): `multiarch-build-check` no es un check obligatorio hoy y su
  propósito es una señal de build multi-arquitectura sobre cambios concretos de dependencias
  o Dockerfile, no un gate universal.
- THE SYSTEM SHALL estructurarlo en dos jobs independientes, `build-backend` y
  `build-frontend`, sin dependencia entre sí y sin job consolidador: cada uno reporta su
  propio check run.

### Scopes de caché disjuntos

- THE SYSTEM SHALL construir cada imagen con `docker/build-push-action@v6`, plataformas
  `linux/amd64,linux/arm64`, `push: false` y `target: prod`.
- THE SYSTEM SHALL usar `cache-from: type=gha,scope=multiarch-backend` /
  `cache-to: type=gha,mode=max,scope=multiarch-backend` para el job de backend, y
  `multiarch-frontend` como scope para el de frontend — **disjuntos entre sí** y disjuntos de
  los scopes que usa `app-deploy-dev` (`deploy-dev` publica solo `linux/arm64`, targets
  coincidentes pero plataformas distintas). Un fallo o contaminación de caché en un scope no
  afecta a los demás workflows.
- THE SYSTEM SHALL usar `mode=max` (no `min`): persiste las capas intermedias del build, no
  solo las finales, así que la siguiente ejecución restaura capas en vez de reconstruirlas.
  Es seguro con `push: false` porque el manifest final no se publica a ningún consumidor
  externo que pudiera confundir una capa cacheada con una imagen válida.

### Invariante de identidad de imagen

- THE SYSTEM SHALL preservar, entre una imagen construida con cache hit y una construida sin
  caché para el mismo SHA, la invariante de identidad que define `app-deploy-dev.md` — la
  composición de identidad de build en el job `provenance` (SHA/revision, versión canónica,
  labels OCI, atributos de provenance) — y que `design.md` (D5, change
  `ci-pr-gates-optimization`) fija como la conjunción de **seis** elementos verificables:
  1. SHA/revision igual al SHA del commit que disparó el build.
  2. Versión canónica `X.Y.Z+YYYY-MM-DD.<7 hex>` en `org.opencontainers.image.version`.
  3. Labels OCI completas (cuatro para backend; tres para frontend), sin sobreescritura ni
     etiquetas inesperadas.
  4. Provenance end-to-end (extractor de PR + validador + suite `provenance-contract`) verde
     para los mismos sujetos.
  5. Build inputs sin cambios: contexto, Dockerfile, build-args, target, plataforma.
  6. Imagen funcionalmente correcta: el job `deploy` de `deploy-dev` levanta la imagen, los
     healthchecks pasan y la sonda de origen desde la red de ingress responde.
- THE SYSTEM SHALL NOT exigir ni verificar reproducibilidad bit-a-bit (digest de manifest,
  digest de capas, `Id`, `RepoDigests`): la invariante de este workflow es la conjunción de
  los seis elementos de arriba, no la identidad binaria de las capas cacheadas.
- IF alguno de los seis elementos falla en una imagen construida con cache hit frente a la
  imagen pre-change del mismo SHA, THEN se considera una regresión y el criterio de rollback
  es "algún elemento de la invariante falla", nunca "el digest difiere".

### Estado del check

- WHILE el repositorio no disponga de protección de rama compatible, THE SYSTEM SHALL ejecutar
  y reportar `build-backend` y `build-frontend` sin configurarlos como checks obligatorios
  para fusionar — mismo motivo de plan de GitHub que el resto de workflows
  (`specs/backend-ci.md` §Estado).

## Key files

- `.github/workflows/multiarch-build-check.yml`.
- `backend/devops/Dockerfile`, `frontend/devops/Dockerfile`.
- `sdd/specs/app-deploy-dev.md` — job `provenance` y la invariante de identidad que este
  workflow preserva sin re-verificar en cada PR.