# BLOCKED — local-dev-network-hardening

Dos entradas abiertas. Ninguna es una decisión pendiente: son verificaciones que necesitan un
recurso que no estaba disponible.

> **Este fichero se reescribió el 2026-08-05 al retirar la guardia de regresión del change.**
> Tenía además todo el registro de cinco rondas de revisión de esa guardia —~19 hallazgos, el
> censo de vías de elusión, las dos que siguen abiertas y el diagnóstico estructural—, y **eso
> viajó íntegro a la entrada `compose-ports-guard` del roadmap**, que es su dueño ahora. No se
> conserva aquí una copia: mantener el mismo hecho en dos sitios fue, literalmente, la causa de
> seis de aquellos hallazgos.

---

## 1. Verificación de red viva (tareas 1.4 y 1.5)

- **Fase**: run
- **Tipo**: `deferred`
- **Qué falta**: comprobar sobre un stack levantado que (a) `docker compose port postgres 5432` y
  `docker compose port redis 6379` devuelven `127.0.0.1`, y `docker inspect` muestra
  `HostIp: "127.0.0.1"`; (b) desde otro equipo de la red (o contra la IP de LAN de esta máquina)
  la conexión TCP a 5432 y 6379 **falla** y a 3000 sigue funcionando; (c) `backend`, `worker`,
  `migrate` y `frontend` siguen alcanzando los datastores por nombre de servicio; y (d) la suite
  ejecutada en el host conecta a `localhost:5432`. Cubre **R1.3, R1.4, R1.5 y R2.1**, los únicos
  criterios del proposal sin verificar.
- **Por qué está bloqueado**: el stack corría desde el directorio principal
  (`/Users/hardcode/personal/AutoHostAI`, proyecto de compose `autohostai`) con los cuatro puertos
  ocupados, mientras **otra sesión implementaba `celery-jobs`** en ese mismo árbol. Este change
  vive en un worktree, que para Docker Compose es un proyecto distinto, así que `make up` aquí
  chocaría; y bajar el stack ajeno le corta el `pytest` a quien está trabajando. Decisión del
  usuario (2026-08-04): **no tocarlo**.
- **Lo que sí está verificado, para no repetirlo**: la *declaración* es correcta —
  `docker compose config --format json` da `host_ip=127.0.0.1` en `postgres` y `redis`, y
  `0.0.0.0` en `backend` y `frontend`. Lo que falta es el comportamiento en red, no el fichero.
- **Intento del 2026-08-05, y por qué no bastó liberar los puertos**: Docker estaba parado, así
  que se arrancó el demonio — y con él **volvió solo el stack de la otra sesión**, porque sus
  contenedores llevan `restart: unless-stopped`. Apareció además un `autohostai-beat-1` que no
  existía antes, señal de que `celery-jobs` ha avanzado. El usuario autorizó tomar la ventana,
  pero **el clasificador de permisos del harness bloqueó tanto `docker stop` sobre los
  contenedores de la otra sesión como la lectura de la IP de LAN** (`ipconfig getifaddr`). No se
  intentó rodear ninguno de los dos bloqueos.
- **Consecuencia de proceso**: esta verificación **no la puede ejecutar el agente** en este
  entorno. Necesita tres cosas que el guardarraíl reserva a la persona: parar contenedores de otra
  sesión, leer la IP de LAN de la máquina, y abrir conexiones TCP contra ella.
- **Guion preparado para ejecutarla de una vez**, con la restauración del stack ajeno en un `trap`
  para que vuelva igual aunque algo falle a mitad, usando `docker stop`/`start` en vez de
  `down`/`up` (conserva los contenedores) y sin rearrancar `migrate`, que es de un solo uso:
  el fichero queda en el scratchpad de la sesión como `verify-1.4.sh`. Cubre R1.1-R1.4 y R2.1.
- **Comando de reanudación**: ejecutar ese guion y pegar su salida, o abrir la ventana a mano y
  volver a `/sdd:run local-dev-network-hardening 1.4`.

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

## Estado de la revisión local

Las secciones 3 y 4 pasaron el panel tras sus arreglos. La sección 1 no tiene panel propio: su
código son tres mapeos de puerto y sus comentarios, revisados de hecho en todas las rondas del
panel completo sin recibir ningún hallazgo. **Los ~19 hallazgos del panel fueron todos de la
guardia**, que ya no está en este change.

Falta cerrar la revisión local con las verificaciones de la entrada 1, que son las que impiden
declarar R1 y R2 completos. Hasta entonces `STATE.md` se queda en `ACTIVE`.
