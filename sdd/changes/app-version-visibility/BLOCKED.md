# Blocked — app-version-visibility

Dos entradas, ambas de la sección 7 (Verification). Ninguna es un problema de la
implementación: las dos exigen infraestructura que no existe en local.

---

## 1. Verificación de la identidad horneada sobre la VM (tarea 7.6)

- **Fase**: run (sección 7)
- **Tipo**: `deferred` — el flujo puede reanudarla, no necesita decisión humana
- **Qué y por qué**: R1.2/R1.4/R1.5/R2.1 piden comprobar sobre el entorno desplegado que
  `docker inspect` muestra los labels OCI en las **dos** imágenes, que `curl` a `/version`
  por túnel SSH devuelve el bloque, y que la cadena coincide con el badge de
  `https://autohostai.digitalsec.work`. Requiere un deploy real, que solo ocurre al mergear
  a `main`.

  **Lo verificable sin desplegar ya está hecho y consta en el registro de la sección 3**:
  build real de la imagen `prod` del backend con build-args (labels presentes, `ENV`
  horneadas, `GET /version` por HTTP devolviendo los seis campos), imagen construida sin
  build-args arrancando y devolviendo `null` en los seis, y build real del frontend `prod`
  confirmando que las server-only quedan en la imagen y que nada server-only aparece en
  `.next/static` ni en el HTML servido.

  Lo que **no** se puede saber hasta el deploy: que el job `provenance` alimenta de verdad
  a los dos builds en un run real de Actions, y que el badge en producción muestra la misma
  cadena que `/version`.
- **Comando de reanudación**: tras el merge y el deploy verde, `/sdd:review app-version-visibility`

---

## 2. El gate `backend-tests` en verde en el Pull Request (tarea 7.7)

- **Fase**: run (sección 7)
- **Tipo**: `deferred`
- **Qué y por qué**: R2.13 exige que el gate esté verde en el PR. Localmente se han
  reproducido **todos** sus pasos con éxito (`make ci-checks`, `alembic upgrade head`,
  `alembic check`, la suite completa: 1203 pasados / 35 saltados), pero el gate en sí solo
  corre cuando el PR existe.

  Un detalle a vigilar en ese primer run, porque es nuevo y no se puede probar en local: el
  step `actions/setup-python@5fda3b95…` (v7.0.0) que se añadió para garantizar `tomllib`.
  Si ese pineado fuese incorrecto, el gate fallaría en cada PR.
- **Comando de reanudación**: abrir el PR y comprobar el run; luego
  `/sdd:review app-version-visibility`
