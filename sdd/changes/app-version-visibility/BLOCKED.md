# Blocked — app-version-visibility

El alcance se recortó el 2026-07-30 a "ver la versión al abrir la app". Con ello
**desaparecieron 14 de los 17 hallazgos** que dejó `/sdd:review`, porque el código que los
producía ya no existe: el panel de procedencia, el endpoint `/version` del backend, el Route
Handler, la extracción del PR y el gate de paridad viven ahora en la entrada de roadmap
`app-version-provenance`.

Quedan dos entradas, ambas por infraestructura que no existe en local. La suite ya se
re-ejecutó sobre el código recortado (backend 1177/35 e idéntico a `main`; frontend 173
tests, typecheck, lint y build de producción limpios; flujo manual comprobado ruta por ruta).

---

## 1. Verificación de la identidad sobre la VM (tarea 4.5)

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

## 2. El gate `backend-tests` en verde en el PR (tarea 4.6)

- **Fase**: run (sección 4)
- **Tipo**: `deferred`
- **Qué y por qué**: solo corre cuando el PR existe. El recorte **revirtió ese workflow a
  `main`**, así que el riesgo que antes anotaba esta entrada —el pineado nuevo de
  `actions/setup-python`— ya no aplica: ese step ya no está. El gate vuelve a ser
  exactamente el que `auth-tenancy` dejó.
- **Comando de reanudación**: abrir el PR y comprobar el run
