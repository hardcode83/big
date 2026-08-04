# Design: ingress-https-hardening

## Context

Hoy `docker-compose.deploy.yml` **no declara ninguna sección `networks`** (verificado: `grep -n networks` no devuelve nada en ninguno de los dos composes), así que los siete servicios viven en la `default` implícita del proyecto y se resuelven todos por nombre entre sí. `cloudflared` (líneas finales del fichero) recibe su routing del edge —`config_src = "cloudflare"`, `specs/ingress-https-dev.md`— de modo que quien tenga el API token puede apuntar un hostname a `http://backend:8000` o `tcp://postgres:5432` sin `apply` ni puerto abierto.

La policy del runner está en `infra/environments/dev/main.tf:196-209`: un primer statement `read secret-bundles … where any {target.secret.id = …}` con cinco OCID enumerados, y un segundo `read secrets in compartment id …` **sin condición**, añadido porque el deploy resuelve el token del túnel por nombre (`.github/workflows/deploy-dev.yml:169-171`, `get-secret-bundle-by-name`). `infra/environments/dev/iam-policy.md` documenta ese segundo statement como "lectura de metadatos" y deja escrito un *"pendiente de verificar en el primer deploy real"*.

El ejemplo peligroso de R3 está en `RUNBOOK.md` §7.4.3, última frase: *"añade `-L 5432:localhost:5432` **y** publica temporalmente el puerto en el compose; recuerda revertirlo"* — sin prefijo `127.0.0.1:`, que es el default `0.0.0.0` de Docker.

Los documentos a corregir por R4/R5 son `docs/adr/0003-https-ingress-dev.md` (restricción 2, la viñeta del API token, la viñeta "A vigilar" y el párrafo final de Trazabilidad), `sdd/steering/infra.md:18` y `docs/ingress-https.md` (§"Cómo llega el tráfico", tercera consecuencia).

## Decisions

### D1 — Dos redes explícitas, `ingress` y `private`; la `default` deja de existir

**Chosen:** declarar ambas en la sección `networks` de nivel superior y asignar **explícitamente** la red de cada uno de los siete servicios, de modo que la `default` implícita ya no se cree. `ingress` = `cloudflared` + `frontend`; `private` = `postgres`, `redis`, `migrate`, `backend`, `worker` + `frontend`. Asignar todos y no solo los dos afectados es lo que hace el control **fail-closed**: si mañana alguien añade un servicio sin sección `networks`, compose vuelve a crear la `default` y ese servicio queda aislado y roto —error visible en el deploy— en vez de aterrizar por defecto en la red que contiene la base de datos.

```
                 internet
                     │
              edge de Cloudflare
                     │  (conexión saliente)
   ┌─────────────────┴──────────────┐
   │ red  ingress                   │
   │   cloudflared ──▶ frontend ────┼──┐
   └────────────────────────────────┘  │
                                       │  frontend es el único servicio
   ┌───────────────────────────────────┴──────────────────┐
   │ red  private                                         │
   │   backend   worker   migrate   postgres   redis       │
   └──────────────────────────────────────────────────────┘
```

Rejected: dejar los otros seis en la `default` y añadir solo `ingress` — funciona igual de bien hoy y falla **abierto** mañana, que es el modo de fallo que este change existe para cerrar.
Rejected: llamar `internal` a la red privada — colisiona con la opción `internal: true` del propio compose, que significa otra cosa (sin salida a internet) y que un lector confundiría con el control aquí descrito.
Rejected: poner `internal: true` en `ingress` — rompería el túnel: `cloudflared` necesita **salida** a internet para abrir la conexión al edge. Merece quedar escrito porque es el error natural dado el nombre.

### D2 — `frontend` es el único servicio en las dos redes; la puerta de salida NO se pinea

**Chosen:** `frontend` se conecta a `private` y a `ingress` (R1.3), y **no** se fija ninguna prioridad de red.

**Corregido durante `run` (2026-08-04), tras una nota del reviewer de seguridad.** La versión aprobada de esta decisión fijaba `priority` en `private` para hacer determinista la ruta de salida por defecto. Eso no era cierto: en Compose, `priority` gobierna **el orden en que el contenedor se conecta a las redes**, y el campo que elige el gateway es `gw_priority` (verificado: Compose v5.1.1 local acepta ambos por separado). La línea escrita no conseguía lo que la decisión pretendía.

Se retira en lugar de sustituirse por `gw_priority`, por dos razones que apuntan igual: no pinear la salida **no cambia nada observable** —el servidor de Next no hace ninguna llamada saliente, todo el fetching de datos vive en componentes cliente—, así que era seguro contra un escenario que no existe; y `gw_priority` es un campo reciente, de modo que una versión de Compose antigua en la VM lo rechazaría al parsear y tumbaría **todos** los deploys, no solo este. Cambiar un campo inefectivo por otro con riesgo de parseo, para asegurar algo que hoy no ocurre, es peor que no hacer nada. El comentario del compose deja escrito cuál es el campo correcto para el día que importe.

Rejected: `gw_priority: 100` en `private` — es el campo correcto, pero introduce riesgo de parseo en la VM a cambio de cubrir un escenario inexistente.
Rejected: mantener `priority` corrigiendo solo el comentario — deja una línea que no hace nada y que el próximo lector interpretará como que la salida está pineada.
Rejected: mover el `frontend` a `ingress` a secas y hablar con el backend por IP publicada en loopback de la VM — reintroduciría dependencia del binding de depuración y rompería `BACKEND_INTERNAL_URL` (R1.3 exige que la aplicación no cambie).

### D3 — El aislamiento no admite excepción por origen, y eso es lo que hereda el camino de los webhooks

**Chosen:** dejar escrito, en el compose (R1.7) y en la documentación viva (R4.5-R4.7), qué alcanza `cloudflared` y qué no. De ahí se sigue el invariante operativo que el change entrega: *cualquier origen público futuro debe ser un servicio conectado a `ingress` que no sea `backend`, **y que no reenvíe hacia `private`***.

**Corregido durante `run` (2026-08-04) por los hallazgos F1-F3 del reviewer de seguridad.** La formulación aprobada tenía tres imprecisiones, y en una sección de endurecimiento la exactitud de lo que se afirma *es* el entregable:

1. **El mecanismo no es el DNS** (F3). Lo que separa las dos redes es el aislamiento **L3** entre bridges: Docker descarta el tráfico entre bridges distintos, así que una regla de ingress no llega ni por nombre ni **por IP literal**. El acotado del DNS interno es una consecuencia. Importa porque una evidencia construida solo sobre `getent hosts` pasaría igual en una topología donde los bridges fueran enrutables entre sí — de ahí la comprobación por IP añadida a D4.
2. **"El frontend y nada más" subestima el radio** (F1, ampliado en la segunda ronda). `cloudflared` sigue alcanzando (a) su **propio loopback**, incluido el endpoint de `TUNNEL_METRICS` con `/ready` y `/debug/pprof` —una regla `http://localhost:2000` se sirve dentro del contenedor y no pasa por ninguna red, así que ninguna separación puede evitarlo— y (b) **el host por el gateway del bridge**, y con él **todo lo que la VM enruta**: los puertos en `0.0.0.0` (hoy el **22**, cuya publicación saltaría el acotado por CIDR del security list), cualquier dirección enrutable de la VCN, y **el servicio de metadatos de la instancia en `169.254.169.254`**. Los bindings a `127.0.0.1` de `backend`/`frontend` siguen fuera de alcance.

   **La fila de IMDS reencuadra lo que el change entrega, y por eso no basta con mencionarla.** Por ahí se obtienen credenciales de *instance principal* y con ellas los cinco secretos del Vault que la policy del runner autoriza —`ENCRYPTION_KEY` (la clave Fernet de la regla 3 de `steering/security.md`), `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, la clave privada de la GitHub App y el token del túnel—. Es decir: el aislamiento de red **aguanta**, pero los datos que R1 pone fuera de alcance quedarían alcanzables por otra vía desde la **misma credencial única** alrededor de la cual se acota todo este change. Verificado en el repositorio que la instancia no desactiva los endpoints legacy (`are_legacy_imds_endpoints_disabled` no aparece en `main.tf`) y que no había ninguna mención a IMDS en la documentación; la **alcanzabilidad** desde la red de ingress es la esperada en Docker sobre cloud pero queda **por medir** en esta VM (comando en `RUNBOOK.md` §7.4.6, ejecutado por la tarea 5.6). Mitigarlo es superficie de la VM y no de esta topología: entrada 2 de `BLOCKED.md`.

   Que este change existiera precisamente para corregir un radio subestimado hacía especialmente caro repetir el error — y se repitió dos veces, primero limitándolo al frontend y luego a "los puertos en `0.0.0.0`".
3. **El invariante iba sobre pertenencia, no sobre reenvío** (F2). Un servicio en `ingress` que reenvíe a `backend:8000` cumple "no ser `backend`" al pie de la letra y devuelve el radio entero. Y esa es la forma que tiene hoy `frontend`, y la primera opción sobre la mesa de `api-ingress-routing` (una `rewrite` de Next). Verificado que hoy no reenvía nada: `frontend/next.config.ts` solo declara `output: "standalone"`, sin `rewrites` y sin `images`, y no hay `middleware.ts`, ni route handlers, ni `"use server"`. Esa ausencia **es parte del control**, y el comentario lo dice, señalando `next.config.ts` como el sitio donde un change futuro haría crecer el radio sin leer nada de este fichero.

   La guarda se enuncia como **clase de superficie** y no como una lista de campos (corregido en la segunda ronda, F5): vale cualquier cosa que haga que el *servidor* de Next emita peticiones. **La enumeración vive en ADR 0003 §Addendum 2026-08-04 §2(b) y este design no la reformula** —extensión de D11 a los artefactos de plan, decidida en la verificación final: la copia que había aquí se quedó con cinco de las seis superficies, y una lista incompleta en el registro de decisión es exactamente la trampa que la guarda quiere evitar—. Nombrar campos concretos en vez de la clase le daría al próximo lector una lista que se puede cumplir mientras se abre el mismo agujero.

Una observación que ni `docs/beds24-spike.md` §"Consecuencia para la infraestructura" ni el análisis heredado de `api-ingress-routing` enumeran, y que se registra **sin elegirla** (R4.7): además de la `rewrite` same-origin de Next, el invariante admite una tercera forma —un servicio receptor propio en `ingress` + `private`, exactamente la topología que hoy tiene `frontend`—. Que exista no la hace la elegida: decidir entre las tres es de `api-ingress-routing`, y las cuatro obligaciones de la regla 12 de `steering/security.md` son de `reservations-webhooks`.

Rejected: relajar R1 aquí de forma "preparatoria" (p. ej. dejar `backend` en `ingress` desde ya) — abriría la superficie antes de existir el control que la protege, que es literalmente el patrón que este change corrige.
Rejected: no mencionar el consumidor futuro — sin el comentario de R1.7 el próximo change lee la separación como un obstáculo accidental y la borra en una línea.

### D4 — La evidencia de R1.4 es de comportamiento, con una imagen que ya está en la VM

**Chosen:** probar el aislamiento con un contenedor desechable atado a cada red, usando `postgres:16` —imagen ya presente en la VM, así que no hay pull— y `getent hosts`:

```bash
P=$(docker compose -f docker-compose.deploy.yml ps -q postgres) # referencia para el inspect
docker run --rm --network autohostai_ingress postgres:16 getent hosts postgres   # DEBE fallar
docker run --rm --network autohostai_private postgres:16 getent hosts postgres   # DEBE resolver
docker inspect -f '{{json .NetworkSettings.Networks}}' <cid-cloudflared>          # solo ingress
```

La prueba se hace sobre la **red**, no sobre el contenedor del túnel, porque `cloudflared` es distroless (sin shell, `curl` ni `wget` — ya documentado en `specs/ingress-https-dev.md`) y no admite `exec`. Como `cloudflared` está atado exactamente a una red, una propiedad de esa red es una propiedad suya. El `docker inspect` aporta la parte estructural que R1.4 pide literalmente; los dos `docker run` la refuerzan con comportamiento observado.

**Reforzado durante `run` (2026-08-04) por F3.** La resolución de nombres no es el control (ver D3), así que a la evidencia se añade un intento de conexión **por IP literal** —la forma que tendría una regla de ingress maliciosa— desde la red de ingress:

```bash
PGIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
        "$(docker compose -f docker-compose.deploy.yml ps -q postgres)")
docker run --rm --network autohostai_ingress postgres:16 timeout 5 bash -c "</dev/tcp/$PGIP/5432"  # DEBE fallar
```

**Procedencia de lo ya reproducido** (añadida en la verificación final, porque la tabla del ADR afirmaba la reproducción sin registrar dónde): los tres pasos se ejecutaron **fuera de la VM**, sobre bridges reales creados al efecto y contenedores desechables, dos veces y de forma independiente — por el implementador durante `run` y por el reviewer de QA en la revisión a escala de feature. Resultado en ambos casos: `getent hosts postgres` **falla** desde la red de ingress y **resuelve** desde la privada, y la conexión cruda por IP a `postgres:5432` **falla** desde ingress y **conecta** desde private (control positivo). Eso acredita el **mecanismo**; el **comportamiento en la VM desplegada** sigue pendiente de la tarea 5.6, y la tabla del ADR lo etiqueta así.

Sin esta comprobación, la evidencia demostraría el acotado del DNS y no el aislamiento. Los pasos quedan escritos en `RUNBOOK.md` §7.4.6 para que sean repetibles tras cualquier cambio de topología, no un hallazgo de una sola vez.

**Segunda corrección (F3 de la segunda ronda): la comprobación necesita un control positivo.** Tal como estaba escrita, cualquier salida distinta de cero caía en la rama `||` y estampaba "OK: bloqueado por aislamiento L3" — incluido el caso de `$PGIP` vacío porque `postgres` no esté levantado, o el prefijo del proyecto sea otro. Es el peor fallo posible en una comprobación de seguridad: un OK sin haber enviado un paquete, justo después de cambiar la topología. Ahora hay guard de `$PGIP` no vacío y el mismo intento **desde `autohostai_private`, que DEBE conectar**, de modo que una ejecución vacua se delata como "los dos bloqueados". Se añade además el comando que **mide** el residual de IMDS en vez de suponerlo.

Rejected: `docker compose exec cloudflared …` — imposible, imagen distroless.
Rejected: demostrarlo reescribiendo una regla de ingress en el edge hacia `postgres` — es exactamente el ataque que el change previene, y se ejecutaría contra el recurso que se está protegiendo.
Rejected: quedarse en el `docker inspect` — describe la configuración, no el efecto; con dos redes recién introducidas conviene ver el `getent` fallar.

### D5 — R2 no se acota: el statement se **elimina**

**Chosen:** borrar el statement `read secrets in compartment id …` y **no tocar la condición** del statement de `read secret-bundles`, que sigue siendo la enumeración de cinco OCID.

**Corregido en el panel de §2 (hallazgos F1/F2 del reviewer de seguridad).** La versión aprobada de esta decisión añadía además `target.secret.name = '…cloudflare-tunnel-token'` al `any {…}`, con el argumento de que "no ensancha nada porque el nombre es único por vault". Ese argumento razonaba en un ámbito **más estrecho que la concesión**: los nombres de secreto son únicos por **vault**, pero el statement se concede `in compartment id ${var.compartment_ocid}`, y ese valor es hoy la **raíz de la tenancy** (verificado en `dev.tfvars`; el propio `.example` dice "raíz de la tenancy, para empezar", e `iam-policy.md` §"Mejora futura" quiere un compartment `dev` justamente para dejar de estar así). Una concesión en la raíz la heredan todos los compartments descendientes, así que la rama por nombre habría dado lectura de **contenido** a cualquier secreto llamado igual en cualquier vault de la tenancy — rompiendo para ese nombre el invariante fail-closed que R2.3 exige preservar, y de forma reproducible sin ataque: basta recrear el vault o levantar un segundo stack con `env = "dev"`.

Y era **innecesaria por mi propia deducción**, que es lo que la convierte en un error y no en una precaución: si OCI resuelve nombre→OCID antes de autorizar, la condición por OCID basta y la rama es código muerto; si no lo resolviera, el deploy no habría podido funcionar nunca desde el 2026-07-29, porque el statement eliminado no concedía `SECRET_BUNDLE_READ`. En los dos casos sobra. El comentario que escribí en `main.tf` ("nunca se comprobó… con las dos condiciones funciona en cualquiera de los dos casos") contradecía además lo que `iam-policy.md` afirmaba tres líneas más allá, en el mismo commit — exactamente la clase de contradicción que mantiene vivo un permiso de más para siempre.

Rejected: `target.secret.name` acotado con `where all {target.secret.name = …, target.vault.id = …}` — cierra el ensanchamiento, pero sigue añadiendo una condición que ninguna operación del deploy necesita.

La razón es que el statement **nunca fue necesario**, no que estuviera mal acotado. Según la referencia de policies de OCI (`docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm`, consultada el 2026-08-04):

| | Permiso exigido | Lo concede |
|---|---|---|
| `GetSecretBundleByName` | `SECRET_BUNDLE_READ` | `read secret-bundles` (statement 1) |
| `GetSecret` / `ListSecrets` | `SECRET_READ` / `SECRET_INSPECT` | `read secrets` (statement 2) |

El deploy solo invoca `secret-bundle get` y `get-secret-bundle-by-name` (`deploy-dev.yml:159-171`); nunca `GetSecret` ni `ListSecrets`.

La incógnita que `iam-policy.md` dejó anotada —si la condición por OCID se evalúa en un acceso **por nombre**— **también queda resuelta, y sin añadir nada**: `GetSecretBundleByName` exige `SECRET_BUNDLE_READ`, permiso que solo concede el statement condicionado por OCID, y el deploy lee por nombre con éxito desde el 2026-07-29, luego OCI resuelve nombre→OCID antes de autorizar. Y si no lo resolviera, ese mismo deploy no habría podido funcionar nunca, porque el statement eliminado no concedía `SECRET_BUNDLE_READ`. En los dos casos la condición por OCID basta, que es lo que hace innecesaria —y por el párrafo de arriba, dañina— la rama por nombre.

Esto **excede R2.1**, que ofrecía "reducir el verbo a `inspect` y/o añadir una condición": aquel menú se escribió antes de comprobar la tabla de permisos, y ambas opciones habrían conservado un permiso que no hace falta. Se cumple *a fortiori*, y conviene decirlo en vez de fingir que se eligió una de las dos.

Rejected: `inspect secrets` sin condición — sigue siendo una concesión sin condición sobre la existencia de todos los secretos del compartment, y además innecesaria.
Rejected: `read secrets … where target.vault.id = <vault>` — conserva un permiso que el deploy no usa; acotar algo que se puede borrar es la respuesta peor.
Rejected: sustituir la enumeración de OCID por nombres — perdería la propiedad fail-closed deliberada de D4 de `app-deploy-dev` (un secreto nuevo es invisible hasta añadirlo), y R2.3 exige preservarla.

### D6 — R2 se verifica con un deploy real, y su radio de fallo es "no hay deploy nuevo"

**Chosen:** verificar por comportamiento (R2.2), en este orden: `plan` → `apply` → lanzar `deploy-dev` por `workflow_dispatch` (el workflow ya lo declara, `deploy-dev.yml:16`) → el paso "Render .env" debe pasar. Es seguro porque ese paso es **el primero tras el checkout** y falla nombrando la clave *antes de tocar contenedores*: una policy equivocada cuesta un deploy fallido, no una caída — los contenedores en marcha siguen intactos y `.env` no se reescribe (el `> .env` ocurre después de las cuatro lecturas).

Si falla, la escalera de R2.5 se recorre en este orden, registrando el motivo: (1) reintentar una vez tras unos minutos, porque las policies de OCI propagan con consistencia eventual y un primer `403` puede ser propagación y no autorización; (2) re-añadir `read secrets` **con** `where target.vault.id`; (3) leer por OCID exponiéndolo como `output`, a costa de una variable de repo que alguien fija tras cada `apply`. El resultado medido —cualquiera de los tres— se escribe en `iam-policy.md` sustituyendo el *"pendiente de verificar"* (R2.4).

**Refinamiento durante `run` (2026-08-04), que estrecha el riesgo sin cambiar la decisión:** la duda que `iam-policy.md` dejó anotada —si la condición `target.secret.id` se evalúa en un acceso *por nombre*— **queda resuelta por deducción sobre el entorno vivo**, no pendiente de medir. `GetSecretBundleByName` exige `SECRET_BUNDLE_READ`, permiso que solo concede el statement condicionado por OCID; el deploy lee el token por nombre con éxito desde el 2026-07-29, así que OCI resuelve nombre→OCID antes de autorizar y el statement eliminado nunca participó en esa autorización. Lo que queda por medir es más pequeño y es **de cliente, no de política**: que el CLI de OCI no haga un `GetSecret` adicional al resolver por nombre. Ninguna condición sobre bundles podría cubrir ese caso —un `GetSecret` exigiría `SECRET_READ` sobre `secrets`—, así que la escalera sigue siendo la mitigación y 5.8 sigue siendo necesaria. **La deducción descansa en una premisa que el repositorio no puede establecer** y que queda declarada en `iam-policy.md`: que la policy versionada sea la única concesión de `SECRET_BUNDLE_READ` que alcance a ese instance principal. Parte de las policies las aplica un admin desde la consola, así que si existiera una a mano, lo que hoy autoriza la lectura podría ser esa; el comando de solo lectura que lo cierra está en `iam-policy.md`.

Rejected: verificar leyendo el `plan` — el `plan` demuestra qué policy se aplicará, no que la autorización funcione.
Rejected: probar la lectura a mano por SSH con `oci --auth instance_principal` antes del deploy — es una comprobación válida y más barata, pero no es la evidencia que R2.2 pide (*"un deploy real cuyo paso Render .env pasa"*); sirve como paso previo, no como sustituto.

### D7 — R3 sustituye el consejo peligroso en vez de solo añadirle el prefijo

**Chosen:** reescribir la última frase de `RUNBOOK.md` §7.4.3 para que el camino recomendado **no publique ningún puerto ni requiera revertir nada**: en Linux el bridge de Docker es enrutable desde el host, así que un cliente gráfico se resuelve reenviando directamente a la IP del contenedor, cuya resolución ocurre en el extremo remoto del `ssh -L`:

```bash
PG=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
       "$(docker compose -f docker-compose.deploy.yml ps -q postgres)")
ssh -L 5432:"$PG":5432 autohostai-dev     # nada publicado, nada que revertir
```

Además se mantiene, como norma explícita del apartado, que **cualquier** publicación temporal de puerto lleva el prefijo `127.0.0.1:` (R3.1) con el por qué remitiendo a D11 de `ingress-https-dev` (R3.3). Es decir: se cumple R3.1 al pie de la letra *y* se retira el consejo que la hacía necesaria, porque el modo de fallo real de R3 no es escribir mal el mapeo, es **olvidar el revert**.

Rejected: limitarse a añadir `127.0.0.1:` — sigue enseñando una edición del compose con revert manual, y un operador en mitad de una incidencia es exactamente quien olvida revertir.
Rejected: dejar solo `docker compose exec postgres psql` — no responde a la pregunta que el apartado plantea (un cliente gráfico en el portátil).

**R3.2 — barrido, verificado y sin más hallazgos.** El único otro `0.0.0.0` en `RUNBOOK.md` y `docs/` es `docs/beds24-spike.md:322`, y **argumenta en contra** de bindear ahí (explica por qué el sink corre en el host). No requiere cambio: el requisito se cumple sin editar nada más, comprobado y no supuesto.

### D8 — ADR por addendum; documentos vivos corregidos en el sitio

**Chosen:** distinguir por naturaleza del documento.

- **`docs/adr/0003-https-ingress-dev.md` es un registro de decisión** → se enmienda con un `## Addendum — 2026-08-04 — …`, siguiendo la convención que ya establece `docs/adr/0001-dev-hosting-provider.md:140`. El addendum recoge R4 (radio real del token tras el aislamiento, y que la config de ingress es remota) y R5 (restricción 2 falsa, la incoherencia de la viñeta "A vigilar"). Las frases afectadas —la viñeta del API token, la restricción 2, "A vigilar" y el párrafo final de Trazabilidad— reciben un puntero de una cláusula al addendum, para que nadie pueda leerlas aisladas y quedarse con lo falso. Reescribir la prosa aceptada borraría que la premisa fue errónea, que es justo lo que hay que dejar registrado; es el mismo motivo por el que R4.4 prohíbe tocar el `design.md` archivado.
- **`sdd/steering/infra.md:18`, `docs/ingress-https.md` y las tres specs son documentos vivos** → se corrigen **en el sitio**, sin addendum ni nota histórica. Una regla de steering que arrastra su propio erratum deja de ser una regla.

Rejected: reescribir las viñetas del ADR en su sitio — pierde el registro del error y, al tocar prosa de una decisión "Aceptado", invita a deriva sobre lo que R5.6 prohíbe alterar.
Rejected: un ADR 0007 nuevo — la decisión (Cloudflare Tunnel) no cambia; abrir un ADR para corregir una premisa infla el log y esconde la corrección lejos del documento que la necesita.

### D9 — Secuencia de ejecución: dos deploys, y el orden importa

**Chosen:** R1 (compose) y R2 (Terraform) son dos ciclos distintos y se ejecutan en este orden, condicionado por una restricción heredada: `plan` y `apply` **solo corren desde `main`** (`specs/infra-dev-terraform.md`), así que no hay `plan` pre-merge.

1. Merge a `main`. El filtro de rutas de `deploy-dev.yml` incluye `docker-compose.deploy.yml`, así que el CD **arranca solo** y despliega la nueva topología de redes → verifica R1 (D4). Corre todavía con la policy antigua, que sigue siendo válida.
2. `infra-dev` con `action: plan`, revisión por logs.
3. `infra-dev` con `action: apply` → la policy queda acotada.
4. `deploy-dev` por `workflow_dispatch` → verifica R2.2 (D6).

Los cambios puramente documentales (R3, R4, R5) no disparan ningún workflow: el filtro de rutas del CD no incluye `docs/**`, `sdd/**` ni `infra/**/*.md`.

Rejected: aplicar la policy antes de mergear el compose — imposible sin `plan`/`apply` desde rama, que `ingress-https-dev` cerró a propósito.
Rejected: un solo deploy que verifique ambos — el deploy que dispara el merge precede necesariamente al `apply`, así que R2.2 exige el segundo de todas formas.

### D10 — Sonda de origen en el CD, porque `up -d --wait` no puede cumplir R1.6

**Añadida durante `run` (2026-08-04)**, tras un hallazgo del reviewer de CI/CD confirmado de forma independiente por el de QA, y con la ampliación de alcance aprobada por el usuario.

**El problema:** R1.6 exige que el deploy falle si el aislamiento rompe la conexión del túnel con el frontend, y el gate existente no puede detectarlo. El healthcheck de `cloudflared` es `cloudflared tunnel ready`, que consulta el endpoint de métricas y solo informa de la conexión con **el edge**; el healthcheck del `frontend` corre **dentro** de su propio contenedor contra `127.0.0.1:3000`. Ninguno de los dos observa si `cloudflared` alcanza el origen. Consecuencia: un change futuro que dejara `frontend` fuera de `ingress` —el modo de fallo que D1 nombra como el más probable— pasaría `up -d --wait` en verde y la URL pública serviría 502 hasta que alguien lo notara. Antes de este change ese fallo era imposible, porque los siete servicios compartían la `default`: el aislamiento **crea** el modo de fallo, así que le toca a este change traer su detección.

**Chosen:** un paso nuevo en el job `deploy` de `.github/workflows/deploy-dev.yml`, después de `up -d --wait`, que corre un contenedor efímero **dentro de la red de ingress** y falla el job si no alcanza `frontend:3000`. Tres detalles que lo hacen barato: la red se **descubre** por `docker inspect` del contenedor de `cloudflared` en vez de cablear `autohostai_ingress` (si mañana cambia el nombre del proyecto o de la red, la sonda sigue probando la red correcta, que es justo la propiedad que interesa); usa la **imagen del frontend** que el `pull` del paso anterior ya ha bajado, así que no añade dependencias ni descargas; y emplea la misma técnica que el healthcheck del propio frontend (`node -e` con `http.get`), cambiando solo el destino de `127.0.0.1:3000` a `frontend:3000` — que es exactamente la diferencia entre "el frontend responde" y "el frontend responde *a quien tiene que responder*".

**Endurecida en la segunda ronda del panel (tres hallazgos del reviewer de CI/CD, todos aceptados):**

1. **La sonda va acotada en el tiempo.** La primera versión no tenía cota alguna, y el healthcheck del que dice copiar la técnica sí la tiene (`healthcheck.timeout: 5s` en el compose). Un origen que acepta la conexión TCP pero no contesta habría dejado el paso colgado hasta el `timeout-minutes: 15` del job y, como su `concurrency` es `cancel-in-progress: false`, **ningún deploy de arreglo podría arrancar detrás**: R1.6 se habría degradado de "falla antes de dar el despliegue por bueno" a "se atasca 15 minutos en medio de un incidente". La forma final —tras la corrección del punto 2— son **dos** cotas: `timeout-minutes: 2` en el paso y un `setTimeout(10000)` en la petición que destruye el socket y sale con 1, más la espera acotada de 20 s del bucle. *(Una versión intermedia envolvía el `docker run` en un `timeout 30`; el punto 2 explica por qué se retiró, y este apartado afirmaba "tres niveles" describiéndolo como vigente hasta que el panel de `review` lo señaló.)*
2. **El contenedor se corta por el daemon, no señalando al cliente.** `--rm` solo limpia cuando el proceso termina, así que una sonda colgada podía dejar un contenedor pegado a la red de ingress —la red que este change trata como frontera de seguridad—.

   **Corregido otra vez en la tercera ronda, porque la segunda respuesta era falsa.** Esta decisión afirmó que "con la cota de (1) el `--rm` siempre llega a ejecutarse", y el reviewer de CI/CD lo refutó midiéndolo: `timeout` envolviendo un `docker run` en primer plano **solo señala al cliente de la CLI** —y sin `--kill-after` ni escala—, y matar el cliente **no para el contenedor**, porque lo gestiona `dockerd`; además un proceso encallado en código síncrono no atiende `SIGTERM`. Ninguna de las tres cotas alcanzaba al contenedor. Impacto real, acotado: **no había riesgo de falso verde** (el `timeout-minutes: 2` del paso lo hace fallar de todos modos) y el contenedor huérfano no escucha en ningún puerto, así que no abre un camino entrante; el daño era un contenedor girando en la red de ingress hasta que el `docker rm -f` del siguiente deploy lo barriera.

   La sonda ahora se lanza **en segundo plano**, se espera su salida con un límite de 20 s consultando `docker inspect`, se recoge su `ExitCode` y, si no ha terminado, se corta con **`docker kill` por nombre contra el daemon** —la única mecánica que el reviewer verificó que sí termina un contenedor encallado— seguido de `docker rm -f`.

   **Tercera corrección, del panel de `review` (CI/CD):** aquella versión seguía dependiendo de que el script llegara a sus líneas de limpieza. Si un comando de `docker` se cuelga por causas **ajenas a la sonda** —`dockerd` cargado, contención de I/O: precisamente lo que ocurre en el incidente que este paso existe para detectar—, Actions mata el **proceso del step** al llegar a `timeout-minutes` y la limpieza no corre; el contenedor, lanzado con `-d` y gestionado por `dockerd`, sobrevive pegado a la red `ingress`. Mi verificación anterior cubría que se cuelgue el **proceso Node**, no que se cuelguen los comandos que lo orquestan, así que este apartado volvía a afirmar más de lo verificado ("deja cero contenedores residuales"). Cerrado con un **`trap … EXIT`** al principio del script, que dispara `docker kill` + `docker rm -f`, **ambos acotados con `timeout -k 0.2 0.8`**. La cota importa y el reviewer la midió sobre el código de `actions/runner`: al cortar un step el runner manda SIGINT (que un bash no interactivo bloqueado en un comando externo **ignora**), espera ~7,5 s, manda SIGTERM —esto sí dispara el trap— y concede solo ~2,5 s antes de hacer SIGKILL del árbol; sin cota, un `docker kill` bloqueado contra el mismo daemon colgado se comería esa ventana y el `docker rm -f` no llegaría a ejecutarse. **El `-k` no es cosmético y lo pidió una cuarta ronda del panel**: `timeout` sin `--kill-after` solo *manda* TERM al vencer el plazo y no fuerza nada — medido, un proceso que ignora TERM sobrevive a `timeout 1` y corre hasta el final (30 s en la prueba), mientras que con `-k 0.2` muere a ~1,2 s por SIGKILL. Con `-k 0.2 0.8` el peor caso de las dos llamadas es 2 × 1,0 s = 2,0 s, dentro de la ventana de ~2,5 s. Es la misma clase de error que las correcciones 2 y 3 de esta decisión —señalar a un proceso no es acotarlo— aplicada esta vez a la limpieza del propio trap. **La garantía es acotada, no incondicional**, y así queda escrita: limpia salvo que `dockerd` esté sin responder dentro de esa ventana, caso en el que el job falla igual pero el contenedor puede quedar hasta que lo barra el `docker rm -f` previo del siguiente deploy. Es la tercera vez que esta decisión afirmaba de más; conviene que sea la última.

   **Cuarta corrección, del mismo panel:** la espera leía `STATE != running` como "terminado", así que un estado transitorio o desconocido se habría interpretado como fin con `ExitCode` 0 por defecto — verde sin que el `http.get` hubiera empezado. Ahora la comprobación es **positiva** (`exited`/`dead`), cualquier otro estado sigue esperando, y un contenedor desaparecido falla explícitamente.

   **Verificado con contenedores reales en los tres casos** tras las correcciones: origen alcanzable → el paso pasa; origen caído → falla el job; sonda deliberadamente encallada en un bucle síncrono → no termina, muere por `docker kill`, deja cero contenedores residuales, y el paso falla. **Alcance de esa verificación, dicho con precisión**: cubre que se cuelgue el proceso de la sonda, no que se cuelgue `dockerd`; para ese caso la garantía es la acotada del punto anterior.
3. **Se exige exactamente una red, en lugar de confiar en el template.** `{{range}}` concatena las claves **sin separador**, así que si algún día `cloudflared` estuviera en dos redes el valor resultante no casaría con ninguna red real: la sonda seguiría fallando (fail-safe, no falso verde) pero con un mensaje que manda a depurar al sitio equivocado. Ahora emite una red por línea y falla con "cloudflared está conectado a N redes, se esperaba exactamente 1". **Verificado localmente bajo bash** contra contenedores reales en los tres casos: una red resuelve, dos redes fallan con ese mensaje, y contenedor ausente falla antes en el guard del `CID`.

Rejected: smoke check público (`curl -fsS https://autohostai.digitalsec.work`) — prueba el camino completo y es la señal más parecida a la del usuario, pero ata el gate del deploy a la disponibilidad del edge, así que un incidente de Cloudflare tumbaría un deploy correcto. Queda como candidato aparte: el panel de `ingress-https-dev` ya señaló que el CD prometía un `curl` que no existe.
Rejected: enmendar R1.6 para que describa lo que el gate detecta — honesto, pero deja vivo un fallo silencioso (verde en CI, 502 en producción) que hoy no existe.
Rejected: cambiar el healthcheck de `cloudflared` para que refleje el origen — `tunnel ready` es del propio binario y no acepta un objetivo; envolverlo exigiría una imagen propia sobre una distroless, justo el mantenimiento que ADR 0003 rechazó al descartar Caddy.

### D11 — El radio y el invariante tienen UN hogar canónico; los demás artefactos apuntan

**Añadida en el panel de `review` (2026-08-04), con la opción elegida por el usuario.** No es una decisión de estilo documental: es la respuesta a un fallo medido.

**El problema, con datos.** La enumeración del radio de daño del API token y el invariante del aislamiento estaban **reescritos en siete artefactos**: el comentario `networks` de `docker-compose.deploy.yml`, el addendum de ADR 0003, `sdd/steering/infra.md`, `RUNBOOK.md` §7.4.6, y —como plan— `BLOCKED.md`, `tasks.md` y este `design.md`. Se corrigieron **tres veces** durante el change (radio limitado al frontend → limitado a los puertos en `0.0.0.0` → completo con IMDS) y **ninguna corrección acertó a la vez en los siete sitios**. El panel de `review` cosechó la factura: cinco hallazgos distintos que son el mismo defecto — `steering/infra.md` sin la fila de IMDS (y es el único documento **normativo** de los cuatro), el compose diciendo "los cinco secretos" y nombrando cuatro, el ADR enumerando 3 de 5 superficies de reenvío, y dos tareas de `tasks.md` prescribiendo todavía la versión repudiada. Y el caso más caro: al reescribir el comentario del compose para corregir el mecanismo, **se eliminó la propiedad de unión de redes** que R4.5 exige registrar, porque vivía solo ahí — dejando dos tareas marcadas `[x]` sobre algo que ya no existía.

**Chosen:** dar a cada uno **un solo hogar canónico** y convertir el resto en punteros.

| Contenido | Hogar canónico | Qué llevan los demás |
|---|---|---|
| Enumeración del radio de daño | ADR 0003 §Addendum 2026-08-04 **§1** (tabla) | una frase de resumen + puntero; **nunca la lista** |
| El invariante, con sus **dos mitades** (pertenencia/unión y reenvío) | ADR 0003 §Addendum 2026-08-04 **§2** | el compose lo resume en dos viñetas porque es donde se edita la topología; el resto apunta |

Cada hogar lleva escrito **que lo es**, con el motivo medido, para que el próximo que corrija sepa dónde hacerlo y no vuelva a repartir la corrección. Los sitios que quedan con contenido propio lo tienen porque es **localmente accionable** y no duplicable: el RUNBOOK conserva los comandos, el compose conserva el invariante resumido y la vía de relajación, `steering/infra.md` conserva la consecuencia normativa ("no se decide dónde vive el token sin leer esa tabla").

Rejected: arreglar los cinco hallazgos editando los siete sitios — es lo que se hizo tres veces, y la cuarta divergencia sería cuestión de tiempo. El propio flujo SDD lo dice: un hallazgo que reaparece en el mismo lugar suele ser un problema estructural, y otra ronda de ediciones no lo arregla.
Rejected: hogar canónico en el comentario del compose — es el sitio que más se edita y el que menos contexto admite, y un fichero de orquestación no es donde se audita una postura de seguridad.
Rejected: hogar canónico en `steering/infra.md` — es normativo y debe decir qué **no se puede hacer**, no arrastrar una tabla de infraestructura que envejece con cada cambio de topología.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Compose de deploy | `docker-compose.deploy.yml` | Sección `networks` con `ingress` y `private`; asignación explícita en los 7 servicios; `frontend` en ambas (sin pinear la salida, D2); comentario de R1.7 (mecanismo L3, alcance real con su residual, invariante sobre reenvío, cómo se relaja, consumidor futuro) |
| CD | `.github/workflows/deploy-dev.yml` | Paso nuevo tras `up -d --wait`: sonda de origen desde la red de ingress que falla el job si `frontend:3000` no responde (D10, R1.6) |
| Terraform | `infra/environments/dev/main.tf:196-209` | Eliminar el statement `read secrets` y **nada más**: la condición del statement de bundles sigue siendo los cinco `target.secret.id`, sin añadidos (ver la corrección de D5). Con eso la `description` "SOLO … (mínimo privilegio)" pasa a ser cierta |
| Doc de IAM | `infra/environments/dev/iam-policy.md` | Statement final, motivo de la eliminación con la tabla de permisos, y retirar el *"pendiente de verificar"* sustituyéndolo por el resultado medido (R2.4) |
| Runbook | `infra/environments/dev/RUNBOOK.md` §7.4.3 | Reemplazar el consejo de publicar puerto por el reenvío a la IP del contenedor; norma del prefijo `127.0.0.1:` con su por qué (R3.1, R3.3) |
| ADR | `docs/adr/0003-https-ingress-dev.md` | `## Addendum — 2026-08-04` con R4 y R5; punteros de una cláusula en las cuatro frases afectadas |
| Steering | `sdd/steering/infra.md:18` | Radio real del API token, corregido en el sitio (R4.1) |
| Doc de capability | `docs/ingress-https.md` | §"Cómo llega el tráfico": la tercera consecuencia deja de afirmar que el navegador nunca llama al backend (R5.5); topología de redes en la explicación del recorrido. §"Limitaciones conocidas": la frase que atribuye a `auth-tenancy` la autenticación de la app pública pasa a describir el estado real (OQ2) |
| Infra (verdad adyacente) | `infra/environments/dev/main.tf` (comentario del security list), `infra/environments/dev/README.md` | Ambos afirmaban que el security list abre 8000/3000 cuando `local.ingress_ports = [22]`. Corregido aquí por la misma razón que R4/R5 —una afirmación de seguridad falsa en un fichero que el change ya toca—, y registrado en la lista de ficheros tocados del proposal |
| Specs | `sdd/specs/ingress-https-dev.md`, `app-deploy-dev.md`, `infra-dev-terraform.md` | Al archivar: topología de redes, statement final, y retirar los tres *"pendiente en `ingress-https-hardening`"* |

## Data & interfaces

Sin cambios de esquema, API, eventos ni variables de entorno. `BACKEND_INTERNAL_URL` sigue siendo `http://backend:8000` y se resuelve por la red `private` (R1.3) — ninguna imagen se reconstruye y el `.env` renderizado por el CD no cambia de forma.

Las redes de compose se crean con el nombre del proyecto como prefijo (`autohostai_ingress`, `autohostai_private`); es el nombre que usan los comandos de verificación de D4 y el que hay que escribir en el RUNBOOK, no el nombre corto del fichero.

## Risks & mitigations

- **Corte público breve en el primer deploy (esperado, una vez).** Cambiar de red obliga a compose a recrear los siete contenedores, incluido `cloudflared`: la app da 502/530 mientras el túnel se reanuncia. Los volúmenes nombrados de `postgres`/`redis` se preservan y `migrate` es idempotente. Mitigación: es dev, y hay dos gates distintos — `up -d --wait` cubre que los siete servicios queden `healthy` (**R1.5**), y la **sonda de origen de D10** cubre que el túnel alcance el frontend (**R1.6**), que es lo que los healthchecks no ven.
- **Que el aislamiento rompa el túnel.** Modo de fallo más probable: `frontend` mal asignado a una sola red, o `internal: true` puesto en `ingress` por confusión de nombre (D1). **Corregido durante `run`:** este apartado afirmaba que eso "se manifiesta como `cloudflared` unhealthy → `up -d --wait` falla el job (R1.6)", y era falso — `up -d --wait` no lo detecta, por el razonamiento de D10. Lo detecta la sonda de origen que D10 añade al CD. Rollback: revertir el commit del compose; el CD redespliega solo.
- **Que `get-secret-bundle-by-name` deje de autorizar.** Radio acotado a "no hay deploy nuevo" (D6), nunca a una caída. Escalera de tres peldaños en R2.5, con la propagación eventual de policies de OCI como primer sospechoso.
- **La IP de contenedor del reenvío de D7 cambia al recrear.** Se resuelve con el `docker inspect` del propio comando en vez de anotarla; queda dicho en el RUNBOOK para que nadie la fije en su `~/.ssh/config`.
- **Red `autohostai_default` huérfana** tras el cambio: compose no siempre la elimina en un `up`. Inocua, pero conviene un `docker network prune` en el RUNBOOK para que un `docker network ls` futuro no sugiera que la topología antigua sigue viva.
- **Que un change futuro deshaga el aislamiento sin darse cuenta.** Es el riesgo que R1.7 y D3 existen para mitigar; el comentario en el compose es la única defensa, porque no hay test que lo cubra.

## Out of scope (confirmado en design)

`docker-compose.yml` (dev local) **no** se toca: no tiene `cloudflared`, así que la separación no aplica, y sus puertos publicados en `0.0.0.0` son de `local-dev-network-hardening`, que es una entrada propia del roadmap con su propia decisión de postura.

## Open questions

Ninguna abierta. Las dos que este design levantó se resolvieron con el usuario en la fase `design` (2026-08-04):

**OQ1 — Alcance del fix de R3: resuelta → sustituir el consejo.** D7 se mantiene tal como está escrito: el RUNBOOK pasa a recomendar el reenvío a la IP del contenedor (nada publicado, nada que revertir) y conserva la norma del prefijo `127.0.0.1:` para cualquier publicación temporal, con lo que R3.1 se cumple igual. Se descartó limitarse a añadir el prefijo, porque el modo de fallo real del apartado es que un operador en mitad de una incidencia olvide el revert, no que escriba mal el mapeo. Contrapartida aceptada: la receta es menos familiar y la IP cambia al recrear el contenedor, así que el comando la saca con `docker inspect` en vez de anotarla (ya recogido en Risks).

**OQ2 — Limpieza adyacente en `docs/ingress-https.md`: resuelta → se corrige de paso.** La frase de §"Limitaciones conocidas" —*"Sin autenticación en el edge. La app es pública; la autenticación del producto llega con `auth-tenancy`"*— entra en el alcance aunque R5.5 no la cubra: el fichero se toca de todos modos y la frase es falsa por la misma clase de razón que R5 corrige, apuntar a un change como si resolviera algo que no resolvió (`auth-tenancy` está mergeado y no tocó el frontend). Mismo criterio con el que R2.4 entró en el proposal. La corrección se limita a describir el estado real —la app pública sigue sin autenticación y el frontend no la tiene todavía— sin prometer dónde llegará, porque hoy ninguna entrada del roadmap la tiene asignada más allá de `dashboard-web`.
