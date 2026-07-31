# Blocked — app-version-visibility

El alcance se recortó el 2026-07-30 a "ver la versión al abrir la app". Con ello
**desaparecieron 14 de los 17 hallazgos** que dejó `/sdd:review`, porque el código que los
producía ya no existe: el panel de procedencia, el endpoint `/version` del backend, el Route
Handler, la extracción del PR y el gate de paridad viven ahora en la entrada de roadmap
`app-version-provenance`.

Quedan tres entradas.

---

## 1. Re-verificar tras el recorte (no ejecutado)

- **Fase**: run / review
- **Tipo**: `deferred`
- **Qué y por qué**: el daemon de Docker se cayó justo después del recorte, así que **la
  suite no se ha vuelto a ejecutar** sobre el código reducido. Antes del recorte estaba en
  1203/35 (backend) y 212/212 (frontend), pero eso ya no describe el árbol actual.

  Lo que hay que correr:
  ```bash
  docker compose exec -T frontend npx vitest run
  docker compose exec -T frontend npm run typecheck
  docker compose exec -T frontend npm run lint
  docker compose exec -T frontend npm run build
  docker compose exec -T backend uv run pytest -q     # debe volver a 1203/35
  ```
  El backend se revirtió a `main` entero (`main.py`, `config.py`, sus dos tests y el
  Dockerfile), así que no debería haber diferencia — pero **no está comprobado**.

  Comprobado sí, estáticamente: no quedan referencias colgantes a nada eliminado
  (`grep` de `provenance`, `extract-pr`, `ci-checks`, `deployment/version`,
  `OPERATOR_SURFACE` sobre `frontend/`, `backend/`, `Makefile`, `.github/`).
- **Comando de reanudación**: con Docker en pie, `/sdd:review app-version-visibility`

---

## 2. Verificación de la identidad sobre la VM (tarea 4.5)

- **Fase**: run (sección 4)
- **Tipo**: `deferred`
- **Qué y por qué**: R1.5 pide comprobar sobre el entorno desplegado que `docker inspect`
  muestra los cuatro labels OCI en **ambas** imágenes con idénticos valores, y que la cadena
  coincide con el badge en `https://autohostai.digitalsec.work`. Requiere un deploy real.

  Lo verificable sin desplegar se hizo durante `/sdd:run` y sigue siendo válido para la
  parte que queda: build real de la imagen `prod` del frontend con build-args, con la cadena
  presente en el HTML servido y nada server-only en `.next/static`.
- **Comando de reanudación**: tras el merge y el deploy verde, `/sdd:review app-version-visibility`

---

## 3. El gate `backend-tests` en verde en el PR (tarea 4.6)

- **Fase**: run (sección 4)
- **Tipo**: `deferred`
- **Qué y por qué**: solo corre cuando el PR existe. El recorte **revirtió ese workflow a
  `main`**, así que el riesgo que antes anotaba esta entrada —el pineado nuevo de
  `actions/setup-python`— ya no aplica: ese step ya no está. El gate vuelve a ser
  exactamente el que `auth-tenancy` dejó.
- **Comando de reanudación**: abrir el PR y comprobar el run
