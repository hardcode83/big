# worktree-port-offset

`make up PORT_OFFSET=<n>` publica los cuatro puertos desplazados, conservando la postura de red (`postgres`/`redis` en `127.0.0.1`, `backend`/`frontend` en todas las interfaces). No está en el plan original, añadida tras `compose-stacks-diagnostic` (2026-08-18).

**Por qué ahora y no antes.** `worktree-parallel-stack` resolvió la colisión **no publicando nada**, y dejó escrito el precio: en un worktree no hay UI ni API en el navegador del host (`specs/local-environment.md:134-136`). Ese aplazamiento se ratificó tres veces —`worktree-parallel-stack` design.md:65 (*«obliga a inventar puertos libres, y "no publicar" no»*), `api-ingress-routing` design D9 (2026-08-08, decidido con Jose), `compose-stacks-diagnostic` proposal.md:69—, y las tres con el mismo argumento: lo que hacía falta se podía sondear **dentro** de la red de compose, porque eran comprobaciones de protocolo. Lo que lo cambia es `hardening-release`, que trae la suite E2E de Playwright: eso es una comprobación **de interfaz**, y el proyecto es mobile-first, con el viewport real comprobado desde un móvil de la LAN.

  **Precisión que evita rehacer el análisis**: esto **no** es para evitar choques de puertos —ya no ocurren— sino para recuperar el navegador que aquella decisión costó, sin reintroducir el choque. Y el desplazamiento es **explícito y determinista**, no aleatorio: un puerto que no sabes de antemano no te deja abrir la URL.

  **Punto de contacto con `compose-ports-guard`**: aquella guardia exime los pares literales `backend:8000` y `frontend:3000`, y un stack desplazado publica `backend:8000+n` / `frontend:3000+n`. Conviene que la guardia aterrice primero y deje la exención expresada como dato y no como estructura.
