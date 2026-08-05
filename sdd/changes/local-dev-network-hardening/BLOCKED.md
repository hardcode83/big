# BLOCKED — local-dev-network-hardening

**Una entrada abierta**, y no es una decisión: es la actualización de specs que el flujo SDD hace
al archivar.

La entrada 1, sobre la **verificación de red viva** (tareas 1.4/1.5), se **resolvió el 2026-08-05**
y se elimina de aquí, que es lo que manda la regla 5 del flujo — por eso la que queda conserva el
número 2. Se pudo hacer porque
el usuario cerró `celery-jobs` y autorizó bajar su stack, liberando los cuatro puertos. Resultado
resumido, con el detalle en las propias tareas: `docker compose port` y `docker inspect` dan
`127.0.0.1` en los datastores y `0.0.0.0`+`::` en `backend`/`frontend`; desde la IP de LAN
(`192.168.100.67`) los puertos 5432 y 6379 **rechazan** mientras 3000 y 8000 conectan; por
loopback los datastores **sí** conectan; `backend`, `worker` y `migrate` siguen llegando por
nombre de servicio; la suite del host conecta por `localhost:5432` (3 passed) y la del contenedor
pasa entera (**2540 passed, 35 skipped**). Con eso **R1.3, R1.4, R1.5 y R2.1 pasan de
«parcialmente cumplido» a cumplido**.

> **Este fichero se reescribió el 2026-08-05 al retirar la guardia de regresión del change.**
> Tenía además todo el registro de cinco rondas de revisión de esa guardia —~19 hallazgos, el
> censo de vías de elusión, las dos que siguen abiertas y el diagnóstico estructural—, y **eso
> viajó íntegro a la entrada `compose-ports-guard` del roadmap**, que es su dueño ahora. No se
> conserva aquí una copia: mantener el mismo hecho en dos sitios fue, literalmente, la causa de
> seis de aquellos hallazgos.

---

## 2. Correcciones de `sdd/specs/` pendientes de archivado

- **Fase**: run
- **Tipo**: `deferred`
- **Qué falta** — ediciones que el flujo SDD hace al archivar, no antes. Sin contarlas: la lista
  es el recuento, y un número aparte que deba cuadrar con ella es la clase de defecto que este
  change ha producido varias veces, esta entrada incluida.

  En `specs/local-environment.md`:
  - **Ganar la postura de red completa**, que hoy no documenta en absoluto: los datastores
    acotados a loopback, `8000`/`3000` en todas las interfaces con su motivo, y **que no hay
    comprobación automática** de esa postura, remitiendo a la entrada `compose-ports-guard`.
  - **Corregir la línea 44**, que repite la afirmación falsa *«es un Postgres solo alcanzable
    dentro de la red de compose»* — es la tercera de las tres copias de esa justificación (D7;
    las otras dos, `steering/security.md` y `README.md:108`, ya están corregidas en este change).

  En `specs/auth-tenancy.md`:
  - **Anotar de qué depende la garantía del throttle** de `:207`/`:215` en dev local: del bind a
    loopback de `redis`, y **no** de autenticación de Redis, que no existe.
- **Por qué no es un descuido**: está registrado con esa precisión en la sección **Affected
  specs** del `proposal.md` (tarea 3.2), justamente para que el archivado no dependa de la memoria
  de nadie.
- **Comando de reanudación**: `/sdd:archive local-dev-network-hardening`, tras el merge.

---

## Candidato para otro change (no se arregla aquí, fuera de alcance)

`sdd/project.md:21` afirma que «`uv` no está instalado en el host», y **sí lo está**
(`/Users/hardcode/.local/bin/uv`, comprobado el 2026-08-05 al ejecutar la suite del host para la
tarea 1.5). Es deriva de un documento de proyecto, no de este change, y tocarlo aquí sería
ensanchar el alcance — pero conviene corregirlo porque el comentario existe justo para decirle a
la gente que no lo intente en el host.

## Estado de la revisión local

Las secciones 3 y 4 pasaron el panel tras sus arreglos. La sección 1 no tiene panel propio: su
código son tres mapeos de puerto y sus comentarios, revisados de hecho en todas las rondas del
panel completo sin recibir ningún hallazgo. **Los ~19 hallazgos del panel fueron todos de la
guardia**, que ya no está en este change.

**Todas las tareas están cerradas** y R1-R4 completos. La única entrada abierta es la de specs, que
por definición se resuelve en `/sdd:archive` y no impide `READY_FOR_PR`.
