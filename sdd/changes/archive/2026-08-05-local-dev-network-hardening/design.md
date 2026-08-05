# Design: local-dev-network-hardening

## Context

`docker-compose.yml` publica cuatro puertos y ninguno lleva prefijo de interfaz:
`postgres` en `5432:5432` (línea 12), `redis` en `6379:6379` (línea 23), `backend` en
`8000:8000` (línea 64) y `frontend` en `3000:3000` (línea 128). Sin prefijo, Docker
publica en `0.0.0.0`. Su gemelo remoto `docker-compose.deploy.yml` sí lo lleva
(`127.0.0.1:8000:8000` en la línea 125, `127.0.0.1:3000:3000` en la 193) y no publica los
datastores en absoluto, con un comentario en la línea 123 explicando el motivo.

Lo que hace explotable la diferencia es que `backend/app/auth/infrastructure/throttle.py`
guarda en ese Redis las tres claves del throttle de login (`login:ip:{ip}` en la línea 34,
`login:fail:{user_id}` en la 52, `login:lock:{user_id}` en las 49 y 61) y el servicio
`redis` de `docker-compose.yml:19-28` no declara `command` ni contraseña — no hay
`requirepass` ni `REDIS_PASSWORD` en ningún fichero del repositorio. Borrar esas claves
desde la red anula la garantía que `specs/auth-tenancy.md:207` y `:215` documentan y que la
regla 7 de `steering/security.md` exige.

Hay dos consumidores del mapeo de Postgres que no se pueden romper:
`specs/domain-foundation-core.md:39` documenta que la suite ejecutada en el host cae al
valor por defecto contra `localhost:5432`, y `README.md:19-20` anuncia
`Postgres: localhost:5432` y `Redis: localhost:6379` como parte del arranque. Ambos siguen
funcionando con un bind a loopback, porque `localhost` **es** esa interfaz.

`sdd/specs/local-environment.md` documenta el stack local con detalle (servicios,
healthchecks, dependencias, `.env`) pero **no menciona los puertos publicados en ninguna
parte** — la postura de red no está escrita, y por eso no había nada que contradecir.

## Decisions

> **Numeración con huecos, y es a propósito.** Este design llegó a tener D1-D12; las ocho que
> faltan (D2-D5, D9-D12) eran **todas de la guardia de regresión**, que se separó a la entrada
> `compose-ports-guard` del roadmap el 2026-08-05 junto con su análisis íntegro. No se renumeran
> las que quedan: cinco rondas de revisión citan estas decisiones por su número, y renumerarlas
> convertiría cada cita en una referencia falsa — exactamente el defecto que D7 documenta.

### D1 — El acotado se hace en la declaración de puertos del compose, no quitando el mapeo

**Chosen:** cambiar los mapeos a `"127.0.0.1:5432:5432"` y `"127.0.0.1:6379:6379"`. Es el
mecanismo que ya usa `docker-compose.deploy.yml` y el que el `RUNBOOK.md:459` fija como
norma general (*«siempre con el prefijo `127.0.0.1:`»*, citando D11 de `ingress-https-dev`),
así que la postura queda expresada en el mismo lenguaje en los dos composes.

Rejected: **eliminar el mapeo y usar `expose:`** — rompe la suite en el host
(`specs/domain-foundation-core.md:39`) y los clientes gráficos que `README.md:19` anuncia.
Rejected: **dejar el mapeo y filtrar en el firewall del host** — imperativo, no
reproducible, y contradice la norma IaC-first igual que se descartó para
`tunnel-host-surface-hardening`.
Rejected: **`network_mode` o red interna sin publicación** — resuelve lo mismo con una
reestructuración de red que ningún requisito pide.

### D6 — Dónde se escribe cada decisión de postura

**Chosen:** el motivo va **junto al mapeo, en `docker-compose.yml`**, en comentario, igual
que `docker-compose.deploy.yml:123` hace con su prefijo; y la postura completa entra en
`specs/local-environment.md` al archivar, en una sección nueva de red que hoy no existe.
El comentario en el compose es lo que lee quien va a editar la línea; la spec es lo que lee
quien quiere entender la postura sin abrirlo.

Tres comentarios, uno por decisión: en `postgres`/`redis` el acotado a loopback (R1); en
`redis` además que la defensa es el bind y **no** la autenticación, que no existe, y que
exponerlo fuera de loopback exige resolverla antes (R2.2, R2.3); en `backend`/`frontend`
que su `0.0.0.0` es deliberado y por qué (R3).

Rejected: **solo en la spec** — la spec no está delante de quien edita el compose.
Rejected: **un documento nuevo en `docs/`** — `steering/documentation.md` reserva
`docs/<capability>.md` para capacidades de producto, y esto es postura de una spec existente.

### D7 — R4 se aplica en tres ficheros, no en uno

**Corregido el 2026-08-04 en la fase `run`:** este design decía «dos ficheros». El barrido de
la tarea 3.3 encontró una **tercera copia**, en `README.md:108` (*«Postgres solo alcanzable
dentro de la red de compose»*), que se corrige también en este change. Dos de las tres se
arreglan aquí (steering y README); la de `specs/` va al archivar. La lección es la del propio
D7: una justificación copiada a mano se propaga a más sitios de los que nadie recuerda, y por
eso el barrido era una tarea y no una suposición.

**Chosen:** la redacción falsa está **triplicada** y las tres copias se corrigen. Son:

1. `steering/security.md:22` — *«inalcanzable desde fuera de `localhost`»*. **En este change.**
2. `README.md:108` — *«Postgres solo alcanzable dentro de la red de compose»*. **En este
   change.** Es la que el barrido de la tarea 3.3 destapó.
3. `specs/local-environment.md:44` — *«no son secretos, es un Postgres solo alcanzable dentro
   de la red de compose»*. **Al archivar**, porque el flujo SDD actualiza las specs entonces;
   registrada con esa precisión en *Affected specs* del `proposal.md`.

Las tres son falsas por la misma razón y las tres se citan como justificación de la misma
exención. Corregir solo una dejaría la mentira viva justo donde la buscaría el siguiente
lector: la spec es lo que consulta quien revisa el stack local, y el README lo que lee quien
acaba de clonar el repositorio.

La corrección **condiciona la redacción a la postura** (R4.3): la exención se justifica
*porque* el mapeo está acotado a loopback, de forma que si alguien lo devuelve a `0.0.0.0`
el texto queda visiblemente sin fundamento en vez de seguir sirviendo de coartada. El
efecto de la exención no cambia (R4.2): la contraseña del Postgres de desarrollo sigue
pudiendo llevar valor por defecto en `.env.example`.

Nota de proceso: `steering/security.md` y `README.md` se editan **en este change**; solo
`specs/local-environment.md` se actualiza **al archivar**, según el flujo SDD.

### D8 — R2 no añade código: es una consecuencia de R1 más su constancia escrita

**Chosen:** R2 no tiene implementación propia. Su criterio 1 lo cumple R1 (si el puerto no
es alcanzable, las claves no se pueden tocar desde la red) y sus criterios 2 y 3 son los
comentarios de D6 más la línea correspondiente en `specs/auth-tenancy.md` al archivar.
Se hace explícito aquí para que no se lea como un requisito sin diseño.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Compose local | `docker-compose.yml` | `postgres` → `"127.0.0.1:5432:5432"`; `redis` → `"127.0.0.1:6379:6379"`; tres comentarios de postura (D6). `8000`/`3000` **sin cambio** de mapeo. |
| Steering | `sdd/steering/security.md` | Reescritura de la exención de la regla 8 (R4, D7). |
| Specs (al archivar) | `sdd/specs/local-environment.md` | Sección nueva de postura de red + corrección de la línea 44 (D7). |
| Specs (al archivar) | `sdd/specs/auth-tenancy.md` | Anota de qué depende en dev local la garantía del throttle (R2). |
| Docs | `README.md` | **Sí se toca**: corrección de la tercera copia de la afirmación falsa (:108, D7), y la subsección nueva de postura de red en `## Arrancar en local`, que dice explícitamente que **esta postura no tiene comprobación automática todavía** y remite a `compose-ports-guard`. Sin recuento a propósito: la lista es el recuento, y mantener un número aparte que deba cuadrar con ella es la clase de defecto que este change ha sufrido seis veces. Las líneas 17-20 (URLs locales) siguen exactas y no cambian. |

## Data & interfaces

Ninguna. No cambia el esquema, ni una ruta de API, ni un evento, ni una variable de
entorno, ni un número de puerto. `DATABASE_URL` y `REDIS_URL` siguen fijadas en
`docker-compose.yml` a `postgres:5432` y `redis:6379` (nombres de servicio en la red de
compose), que es un camino distinto del mapeo publicado y no se ve afectado
(`specs/local-environment.md:28`).

## Risks & mitigations

- **Alguien tiene una herramienta apuntando a la IP de LAN del portátil.** Un cliente
  gráfico configurado contra `192.168.x.y:5432` deja de conectar. Mitigación: es
  precisamente el acceso que el change elimina; `README.md:19` ya documenta `localhost` como
  la vía, y el `RUNBOOK` documenta el reenvío por SSH para el entorno remoto.
- **La suite del backend ejecutada en el host.** Riesgo aparente, no real:
  `specs/domain-foundation-core.md:39` la hace caer a `localhost:5432`, que es la interfaz
  a la que queda acotada. R1.5 lo fija como criterio para que se verifique y no se suponga.
- **La postura se revierte sin que nadie lo note.** Es el riesgo que la guardia iba a cubrir y
  que la separación deja **abierto y asumido**: hoy solo lo atrapa la revisión del diff de un PR
  que toque `docker-compose.yml`. Mitigación parcial, deliberadamente débil: está dicho en los
  tres sitios donde alguien lo leería —el comentario junto a cada mapeo, `README.md` §Postura de
  red y la regla 8 de `steering/security.md`—, y los tres remiten a `compose-ports-guard`. Se
  acepta porque la alternativa era enviar una guardia con dos vías de elusión demostradas, que es
  peor que no tenerla: daría una garantía falsa.
- **Contenedores en la misma red de Docker siguen alcanzando los datastores.** El bind a
  loopback acota la publicación en el *host*, no la red de compose. Es intencionado (R1.4) y
  no un residual: lo que se cierra es el acceso desde otras máquinas.

## Open questions

Ninguna abierta. Las dos que este design levantó (alcance y forma de la guardia) se resolvieron
con el usuario el 2026-08-04, y **ambas viajaron con la guardia** a la entrada
`compose-ports-guard` cuando se separó: sus respuestas son ahora entrada de diseño de aquella, no
de esta.
