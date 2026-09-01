# AutoHostAI

Capa operativa inteligente sobre un PMS/Channel Manager externo para viviendas turísticas. Ver `docs/AutoHostAI_PRD_v5_Claude.md` para el PRD completo y `sdd/` para el flujo de desarrollo (Spec-Driven Development).

## Arrancar en local

Requisitos: Docker + **Docker Compose ≥ 2.35.0**, **git ≥ 2.31**, `make`.

De dónde salen los suelos: git 2.31 trae el `--path-format` con el que `make up` distingue un worktree enlazado del principal (por debajo, la detección falla hacia «publicar», así que un worktree chocaría de puertos en vez de arrancar sin ellos). El de Compose lo fijan tres cosas y manda la mayor: 2.24 introdujo el tag `!reset` que usa `docker-compose.worktree.yml`, 2.24.4 el tag `!override` que usa el overlay que genera `make up PORT_OFFSET=<n>`, y **2.35.0 la bandera `--no-env-resolution`** con la que `make check-compose-ports` inspecciona la postura de red sin necesitar `.env`. Por debajo del suelo esa guardia sale en rojo avisando de la versión, no en verde.

```bash
make up   # levanta todo el stack: postgres, redis, backend, worker, beat, frontend
```

Sin pasos previos: `make up` crea `.env` automáticamente desde `.env.example` (valores locales por defecto, sin secretos reales) si no existe todavía, y **genera en él la clave de firma JWT** con `openssl rand -hex 32` si falta — el valor se queda en tu máquina y nunca vive en el repositorio. Las migraciones de base de datos (Alembic) también se aplican solas — un servicio `migrate` corre `alembic upgrade head` antes de que `backend`/`worker`/`beat` arranquen.

Al cabo de unos segundos:

- Backend (FastAPI): http://localhost:8000/health — API en http://localhost:8000/api/v1, documentación navegable en http://localhost:8000/docs
- La misma API, **en el origen del frontend**: http://localhost:3000/api/v1 — la sirve un proxy same-origin (`frontend/app/api/[...path]/route.ts`), que es el camino que usa el navegador y el único que existe en el entorno desplegado. Enruta **solo** `/api/`: `/docs` y `/openapi.json` no viajan por ahí a propósito, así que para la documentación navegable usa el puerto 8000 de arriba. Ver [`docs/ingress-https.md`](docs/ingress-https.md)
- Frontend (Next.js): http://localhost:3000 — Application Shell; `/` resuelve la **landing pública** o el redirect según el bit de presencia `autohostai.session.present`: cookie ausente → landing directo sin red; cookie presente → el Server Component pregunta al backend `GET /api/v1/auth/me` (timeout 2 s); 2xx → `307` a `/dashboard`; 401 → purga la cookie y renderiza la landing (defensa contra JWT revocado con cookie persistente); 5xx o timeout → `307` a `/dashboard` sin tocar la cookie (un fallo del backend no equivale a logout). Ver `sdd/specs/frontend-auth-role-routing.md` §«Server-side discrimination of a stale presence cookie at the application root». El **dashboard** (`/dashboard`) y el **detalle de propiedad** (`/properties/[id]`) son funcionales en modo solo lectura **salvo la sección de desajustes de la card del dashboard**, que desde `blocked-transitions-web` ofrece al `PROPERTY_MANAGER` cancelar la limpieza o resolver la incidencia que están bloqueando la siguiente entrada — la propietaria ve el aviso con su `READ_PROPERTIES` pero no los botones (ver [`docs/dashboard.md`](docs/dashboard.md) y [`docs/properties.md`](docs/properties.md) §«Aviso de desajustes en la card del dashboard»); el **listado de propiedades** (`/properties`) es el índice del portfolio en modo solo lectura — seis columnas, filtros por `status` y estado operacional, paginación, y el nombre enlazando al detalle; el alta, la edición y la retirada quedan fuera de alcance desde la web (ver [`docs/properties.md`](docs/properties.md) §«Ver el portfolio desde `/properties`»); la **pantalla de reservas** (`/reservations`, con su detalle `/reservations/[id]`) lista y abre reservas del tenant en modo solo lectura — filtros por `status` y rango de fechas `date_from`/`date_to`, paginación; la escritura (`POST`/`PATCH`/`DELETE`) queda fuera de alcance desde la web (ver [`docs/reservations.md`](docs/reservations.md)); la **pantalla de incidencias** (`/incidents`, con su detalle `/incidents/[id]`) lista y abre las del tenant en modo solo lectura — filtros por `status` y `severity`, paginación; las once mutaciones (`classify`, `triage`, `assign`, `accept`, `start`, `wait-parts`, `resume`, `resolve`, `cancel` y `PATCH /incidents/{id}`) y la respuesta de aprobación (`POST /owner-approvals/{id}/respond`) quedan fuera de alcance **desde esta pantalla** — seis de ellas las conduce la app del técnico, más abajo (ver [`docs/maintenance.md`](docs/maintenance.md)); la **app del técnico** (`/tech`, con su detalle `/tech/incidents/[id]`) es funcional contra el backend real — la lista de las incidencias asignadas con la vivienda de cada fila, el ciclo del técnico (`accept`, `reject`, `en-route`, `wait-parts`, `resume`), el cierre con coste y materiales (`resolve`), la galería y la subida de fotos antes/después, y la puerta de aprobación de la propietaria tal como la resuelve el backend (ver [`docs/maintenance.md`](docs/maintenance.md) §«La app del técnico»); el **portal del huésped** (`/guest/[token]`) es funcional contra las cuatro rutas anónimas del backend, sin cuenta ni JWT (ver [`docs/guest-portal.md`](docs/guest-portal.md)); las **limpiezas** (`/cleaning`) son funcionales contra el backend real — lista paginada con filtros por vivienda y estado, y asignación/reasignación para el `PROPERTY_MANAGER` (ver [`docs/cleaning.md`](docs/cleaning.md) §«Operar las limpiezas desde `/cleaning`»); la **app de la limpiadora** (`/cleaner`, con su detalle `/cleaner/tasks/[id]`) es funcional para el rol `CLEANER` — la lista «mis tareas» con la vivienda y la ventana de cada fila, el detalle con piso + checklist + categorías de foto + galería, el ciclo del rol (aceptar / rechazar / iniciar / completar), el marcado de ítems del checklist, la subida de fotos por categoría con sus mensajes de error localizados, y el reporte de incidencia inline (ver [`docs/cleaner.md`](docs/cleaner.md)); el **historial de una vivienda** (`/timeline`) monta el mismo timeline que el detalle de propiedad sobre la vivienda que elijas en un selector — vocabulario cerrado de tipos de evento, filtros por actor y severidad, rango de fechas y paginación; el backend solo sirve el historial de una vivienda a la vez, así que no hay timeline global (ver [`docs/dashboard.md`](docs/dashboard.md)); los **precios recomendados** (`/pricing`) son funcionales contra el backend real — dos pestañas bajo la misma ruta: la **cola de recomendaciones**, con filtros por vivienda, rango de fechas y estado, paginación, los tres movimientos de decisión (aprobar, rechazar y marcar como publicada) para el `TENANT_OWNER` y el `PROPERTY_MANAGER`, y la regeneración bajo demanda; y las **reglas** que los producen, en modo solo lectura con filtros por vivienda y actividad — el interior de sus columnas JSONB se cuenta, nunca se pinta (ver [`docs/pricing.md`](docs/pricing.md)); el resto de rutas de módulos muestran un placeholder "en preparación". El *shell* renderiza sin backend; las superficies que consumen la API (propiedades, reservas, incidencias, app del técnico, portal del huésped, limpiezas, timeline y precios recomendados) muestran su estado de error accesible si no está disponible.
- Postgres: localhost:5432 — ya con el esquema de dominio creado (`tenants`, `users`, `properties`, `guests`, `reservations`, `timeline_events`, ...)
- Redis: localhost:6379
- Ficheros subidos (hoy solo las fotos de limpieza): volumen con nombre `backend_media` montado en **`/app/media`** y **solo en el servicio `backend`**, que es el único que escribe y sirve ficheros. Es un volumen y no un bind del árbol a propósito: `/app` ya está bindeado al repositorio, así que un directorio suelto haría aparecer las fotos en `git status`.

```bash
make bootstrap         # crea el tenant y los usuarios iniciales (ver abajo)
make seed-demo         # llena ese tenant con el dataset de demo (ver abajo); exige bootstrap antes
make demo-reset        # resetea el tenant de demostración de `dev` (ver abajo); exige DEMO_ACCOUNT_PASSWORD
make openapi           # regenera el contrato de API (ver abajo)
make check-version-parity # comprueba VERSION, backend y frontend
make compose-stacks    # lista los stacks de Compose de la máquina y marca los huérfanos (ver abajo)
make check-compose-ports # comprueba la postura de red del compose local (ver abajo)
make down              # para y elimina los contenedores del stack
make logs               # sigue los logs de todos los servicios
make ps                  # estado de los contenedores
make ports               # desplazamiento vigente y los cuatro mapeos efectivos (ver abajo)
```

`make down` conserva los volúmenes. **`docker compose down -v` no**: se lleva la base de datos *y* `backend_media`, es decir, todas las fotos subidas. Es un stack de desarrollo y no hay copia de seguridad de nada de eso, así que conviene leerlo aquí antes de descubrirlo (ver [`docs/cleaning.md`](docs/cleaning.md) §«Dónde viven las fotos»).

Las URLs de arriba son las del **worktree principal**. Un worktree enlazado de git levanta su propio
stack en paralelo y **por defecto sin publicar puertos**, así que ahí no hay nada que abrir en el
navegador del host — la suite sí corre, porque va por la red de compose. `make up` te dice en qué modo
arranca. Detalle y coste en `sdd/project.md` §«Worktree bootstrap».

Cuando sí necesitas el navegador desde un worktree —comprobar la UI, abrirla desde un móvil real de
tu LAN— la salida es **desplazar los cuatro puertos**:

```bash
make up PORT_OFFSET=10   # postgres 5442, redis 6389, backend 8010, frontend 3010
make ports               # qué desplazamiento tiene el stack que está corriendo
```

Un solo número describe el stack entero, la interfaz de cada servicio se conserva (`postgres` y
`redis` siguen acotados a `127.0.0.1`; `backend` y `frontend` siguen en todas las interfaces, que es
lo que permite abrirlo desde el móvil por la IP de esta máquina) y dos worktrees con desplazamientos
distintos conviven publicando. Funciona también en el worktree principal, con un matiz que se lee mal
si no está escrito: **ahí desplazar no crea un segundo stack, mueve el que hay** — el nombre de
proyecto sale del directorio, así que `make up PORT_OFFSET=<n>` recrea esos servicios en los puertos
nuevos. `make up` lo anuncia al arrancar.

Sin `PORT_OFFSET` —o con `PORT_OFFSET=0`— no cambia absolutamente nada.

Tres cosas que conviene saber antes de usarlo:

- **`make down`, `logs`, `ps` y `sh` no necesitan que repitas el número.** Direccionan el proyecto por
  su nombre, no por sus puertos. El único que lo necesita es `up`, porque es el único que crea los
  mapeos — así que un **`make up SERVICE=<x>` parcial sin repetir `PORT_OFFSET`** recrearía ese
  servicio **sin puertos**. Repítelo o levanta el stack entero.
- **`FRONTEND_BASE_URL` no se desplaza sola.** Su valor por defecto es `http://localhost:3000`, así
  que en un stack desplazado el enlace de recuperación de contraseña sigue apuntando al frontend del
  puerto 3000 —el de otro stack— hasta que la ajustes en tu `.env`. Para un móvil de la LAN un
  `localhost` tampoco valdría, así que ahí hay que ponerle la IP de la máquina de todas formas.
- **El desplazamiento no toca la guardia de puertos.** El overlay que lo aplica se genera en
  `.make/docker-compose.offset.yml`, gitignorado, y se carga **solo con `-f` explícito**, así que un
  `docker compose` desnudo —que es como invoca `make check-compose-ports`— no lo ve nunca y su
  veredicto sigue siendo función solo del repositorio.

### Postura de red del stack local

`docker-compose.yml` publica `postgres` y `redis` **solo en `127.0.0.1`**: no son alcanzables
desde otros equipos de tu red, solo desde esta máquina (`localhost:5432` y `localhost:6379`
siguen funcionando igual, incluida la suite ejecutada en el host). No es higiene: ese Redis
guarda los contadores del límite de intentos de login, y quien pueda borrarlos entre intentos
anula el límite de 10/min por IP y el bloqueo tras 10 fallos.

`backend` (`8000`) y `frontend` (`3000`) sí publican en **todas** las interfaces, y es
deliberado: es lo que permite abrir la app desde un móvil real por la IP de tu LAN, que es
como se comprueba el diseño mobile-first. Así que el stack local no es "invisible desde la
red" — la UI y la API sí lo son; el acceso directo al datastore, no.

**Esta postura se comprueba sola**: `make check-compose-ports` en local, y el check `compose-ports`
en cada Pull Request. Si alguien publica un puerto sin el prefijo `127.0.0.1:`, sale en rojo
nombrando el servicio y el mapeo, en vez de depender de que alguien lo vea en el diff. Exime
exactamente los dos pares del párrafo anterior —`backend:8000` y `frontend:3000`—, y por **par**, no
por servicio: un puerto extra en `backend` falla igual. Contrato completo y limitaciones conocidas en
`sdd/specs/local-environment.md` §«Guardia de la postura de red».

**Ojo con el alcance, para no leerlo de más**: lo que esto protege es el acceso *desde la red*.
Redis corre sin `requirepass`, así que otro proceso de tu propia máquina sí puede tocar esos
contadores; se acepta porque es una máquina de desarrollo con datos de prueba.

**Los cuatro mapeos son del worktree principal.** Un worktree enlazado de git levanta su stack
**sin publicar ninguno**: `make up` añade allí `docker-compose.worktree.yml`, que los retira con
`ports: !reset []`, y comprueba antes de levantar que en la configuración resuelta no queda **ningún
mapeo de puertos declarado** — no solo ninguno con puerto de host explícito, porque hay formas de
`ports:` que Docker publica en un puerto efímero sin declararlo. Los mapeos siguen
declarados en `docker-compose.yml` a propósito, y no en un fichero aparte: es esa declaración la que
describe la postura de red del proyecto, la que ve un `docker compose config` desnudo y la que
`make check-compose-ports` comprueba en cada Pull Request.

**Y la postura se conserva desplazada.** Con `make up PORT_OFFSET=<n>` cambia el puerto de host de los
cuatro y **nada más**: `postgres` y `redis` siguen publicando únicamente en `127.0.0.1` —que es lo que
sostiene todo el párrafo de arriba—, `backend` y `frontend` siguen en todas las interfaces, y
`worker`, `beat` y `migrate` siguen sin publicar nada. `make up` lo comprueba **antes de levantar**,
sobre la configuración resuelta y por igualdad exacta del conjunto de mapeos, y además sondea los
cuatro puertos **en IPv4**: si uno está ocupado aborta nombrando puerto y servicio, en vez de dejar
que Compose falle a medio arrancar. Que el sondeo sea solo IPv4 es una limitación aceptada y no un
descuido — un puerto ocupado *únicamente* en `::` lo atraviesa y falla al levantar, con el error de
Compose en vez del mensaje propio. La resolución por nombre de servicio dentro de la red de compose no ve el
desplazamiento en absoluto (`backend:8000`, `redis:6379`), así que ni el proxy `/api/` del frontend ni
la suite del backend cambian.

**Consecuencia práctica para los `docker compose` desnudos de este README**, y conviene ser preciso
porque no afecta a todos igual. En el worktree principal valen todos, porque ahí `make` tampoco pasa
`-f`. En un worktree enlazado solo importan los que **crean** contenedores, que cargarían el fichero
base e intentarían publicar los cuatro puertos:

- `docker compose up ...` (Migraciones usa `docker compose up -d postgres`) → usa `make up SERVICE=postgres`.
- `docker compose run ...` **cuando arrastra dependencias**, y aquí está el caso que más engaña:
  `run` no publica lo suyo, pero su `depends_on` toca `postgres`/`redis` — y **tenerlos ya levantados
  no protege**. Compose recrea una dependencia cuyo hash de configuración no coincide con la que está
  corriendo, y un `docker compose` desnudo en un worktree calcula la configuración del fichero base,
  *con* los cuatro mapeos. **Medido**: con la dependencia viva y sin puertos, un `run` desnudo imprime
  `Recreate` y la deja publicando. Así que desde un worktree la única salida es que el conjunto de
  ficheros coincida (ve por `make`, que añade el overlay) o `--no-deps` si el comando no necesita la
  base de datos — que es exactamente por lo que `make openapi` lo lleva.
- `docker compose exec`, `logs`, `ps`, `down` → **no crean nada**, actúan sobre los contenedores ya
  vivos del proyecto, y funcionan igual desde un worktree. Por eso el
  `docker compose exec backend uv run pytest` de §Tests es correcto en los dos sitios.

Lo que un stack abandonado retiene no son puertos, sino **disco**: un worktree enlazado no publica
ninguno (`ports: !reset []`), así que el único que puede chocar de puertos es el stack del worktree
principal. Bajar un worktree sin bajar su stack deja volúmenes e imágenes vivos y sin nada que los
explique.

`make compose-stacks` los lista todos con su directorio de origen y los marca: `vivo` (worktree
registrado en git, con su rama), `huérfano` (bajo el árbol de este repositorio, pero ese worktree ya
no está registrado), `ajeno` (fuera del árbol) o `indeterminado` (Docker no da un origen resoluble).
Informa y nada más: no baja stacks, no borra volúmenes y no imprime ningún comando para pegar.

### Levantar un solo componente

`SERVICE=` es opcional en `up`/`down`/`logs`/`sh`. Compose arranca automáticamente las dependencias declaradas de ese servicio:

```bash
make up SERVICE=backend    # backend + postgres + redis (sin frontend)
make up SERVICE=frontend   # frontend + backend + sus dependencias
make sh SERVICE=backend    # shell dentro del contenedor de backend
```

## Entrar en la aplicación

El producto no tiene registro público, así que los usuarios iniciales se crean con un
comando. Rellena los `BOOTSTRAP_*` de tu `.env` (van sin valor a propósito: son
contraseñas de personas) y ejecuta:

```bash
make bootstrap   # crea el tenant, su config y dos usuarios: TENANT_OWNER y PROPERTY_MANAGER
```

Es idempotente y falla antes de escribir nada si falta alguna variable. No está
enganchado a `make up` para que el arranque siga sin pasos manuales.

Con eso ya se puede entrar, pero el producto está vacío: ni viviendas, ni reservas, ni
plantilla de limpieza. El tercer paso lo llena con el dataset de demo de PRD §27:

```bash
make seed-demo   # dos viviendas, dos cuentas más (CLEANER y TECHNICIAN), tres reservas, la plantilla de limpieza, tres incidencias y una limpieza cerrada con sus fotos
```

**Exige un tenant ya creado**: completa el que `make bootstrap` dejó, y si no lo encuentra sale
con error nombrando ese comando, sin escribir nada. Necesita sus propias variables
(`SEED_CLEANER_*`, `SEED_TECHNICIAN_*`), también vacías en `.env.example` y sin valor por
defecto en ninguna parte.

Ojo con una cosa que sorprende: los correos que PRD §27 publica para la propietaria y la
manager (`owner@adamar.test`, `manager@adamar.test`) **son los que tú pusiste en tu `.env`**,
no algo que el comando imponga — los busca por rol. Todo lo demás, incluida la receta para
refrescar un dataset que ha envejecido: [`docs/seed-demo.md`](docs/seed-demo.md).

Hay además un **segundo tenant**, `AutoHostAI Demo`, que existe para enseñar el producto a alguien
de fuera sin darle las cuentas del equipo: cuatro credenciales publicables y un reset diario que lo
devuelve a su estado inicial con las fechas del día. Su comando es idempotente en el mismo sentido
que los otros dos —aprovisiona si no existe, resetea si existe— y nombra su tenant por una constante
del módulo, así que **no hay forma de apuntarlo al tenant de trabajo**:

```bash
make demo-reset   # borra, converge las cuatro contraseñas y vuelve a sembrar, con las fechas de hoy
```

Necesita `DEMO_ACCOUNT_PASSWORD` en tu `.env` (vacía en `.env.example`, sin valor por defecto en
ninguna parte) y se niega a escribir nada si falta o tiene menos de 12 caracteres. En `dev` la sirve
el OCI Vault y la pasa un workflow programado. Quién es quién, **qué no es demostrable todavía**,
cómo se cambia la contraseña y qué hacer cuando el reset sale en rojo:
[`docs/demo-tenant.md`](docs/demo-tenant.md).

A partir de ahí **el resto de las cuentas se dan de alta por API**, sin volver a tocar la
máquina: `POST /api/v1/users` crea el usuario y devuelve una contraseña temporal una sola vez.
El bootstrap sigue siendo lo único que da la primera entrada a un entorno nuevo.

Endpoints de auth: `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`,
`POST /api/v1/auth/logout`, `GET /api/v1/auth/me`. Operación, configuración del límite de
intentos y las cosas que sorprenden: [`docs/auth-tenancy.md`](docs/auth-tenancy.md).

Autoservicio de contraseña: `POST /api/v1/auth/change-password` (con sesión),
`POST /api/v1/auth/forgot-password` y `POST /api/v1/auth/reset-password` (anónimos). Quien
recibe una contraseña temporal —del bootstrap, de `POST /api/v1/users` o del rescate de abajo—
queda con `must_change_password`, y hasta que la cambie toda petición autenticada responde
`403 PASSWORD_CHANGE_REQUIRED` salvo `me`, `logout` y `change-password`. **El aviso de
recuperación no llega todavía a nadie**: el canal de correo es el adapter de consola, al que se
le prohíbe registrar el enlace, así que el SMTP real llega con `hardening-release` y hasta
entonces la vía que recupera una cuenta es el comando de rescate. Política de contraseña, los
tres endpoints y ese procedimiento:
[`docs/auth-account-recovery.md`](docs/auth-account-recovery.md).

Administración del tenant: `/api/v1/users` (alta, listado, edición, baja, reset de contraseña)
y `/api/v1/tenants/{id}` (datos del tenant y sus umbrales, SLAs y ventanas). Quién puede hacer
qué y qué rastro deja: [`docs/user-management.md`](docs/user-management.md).

Inventario de viviendas: `/api/v1/properties` (alta, listado paginado, detalle y edición). Es lo
que hay que hacer **antes** de poder crear ninguna reserva, porque toda vía de entrada —el alta
manual, el import CSV y el sync del PMS— resuelve la propiedad primero. Quién puede darlas de
alta, cómo se retira una sin borrar historial y por qué la contraseña del wifi no se puede leer
de vuelta: [`docs/properties.md`](docs/properties.md). El listado tiene pantalla desde
`properties-web`: `/properties` lo sirve en modo solo lectura, con filtros por `status` y estado
operacional y paginación; el alta y la edición (`POST`/`PATCH`) siguen siendo sólo API.

## Migraciones (Alembic)

El esquema se aplica solo al arrancar (`make up` → servicio `migrate`). Para cambiarlo:

```bash
cd backend
uv run alembic revision --autogenerate -m "descripción del cambio"   # genera una migración
uv run alembic upgrade head                                          # aplica pendientes
uv run alembic downgrade -1                                           # revierte la última
```

Requiere Postgres alcanzable (`make up` levantado, o al menos `docker compose up -d postgres`).

## Contrato de API (OpenAPI)

`backend/openapi.json` es el contrato de la API, versionado en el repositorio. Es lo que
consume el frontend para saber la forma de cada endpoint, y el sitio donde un cambio de
respuesta se ve en el diff del Pull Request que lo provoca.

```bash
make openapi   # regenéralo tras cambiar la forma de una respuesta
```

No necesita el stack levantado: la generación no toca base de datos, Redis ni red. El
workflow `api-contract` lo comprueba en cada PR y falla si el fichero commiteado ya no
corresponde al código, indicando este mismo comando.

El frontend consume el contrato mediante el generador fijado
`openapi-typescript@6.7.6`. Desde `frontend/`, `npm run api:generate` regenera
`frontend/lib/api/generated/openapi.d.ts` y `npm run api:check` comprueba que el artefacto
versionado no ha derivado. Ambos comandos usan Node 22, `npm ci` y la misma implementación
versionada en macOS, Linux y CI. El workflow `frontend-api-contract` ejecuta ese check en cada
PR y push a `main`; si hay diferencias muestra el diff y el comando de regeneración.

El cliente permanece genérico y solo expone tipos derivados de OpenAPI: no crea wrappers por
endpoint ni conecta todavía el dashboard al backend real. El workflow `api-contract` del backend
continúa comprobando por separado que `backend/openapi.json` corresponde al código backend.

La documentación interactiva sigue disponible en http://localhost:8000/docs con el stack
levantado.

La procedencia privada del build y sus verificaciones operativas están descritas en
[`docs/app-version-provenance.md`](docs/app-version-provenance.md). El módulo backend vive en
`backend/app/provenance/`; sus metadatos no se publican en la configuración ni en el HTML del
frontend.

## Variables de entorno

Ver `.env.example` — trae valores por defecto funcionales para config local sin sensibilidad real. Lo que hace aceptable ese default de Postgres es que `docker-compose.yml` publica `postgres` y `redis` **solo en `127.0.0.1`**, así que la base de datos no es alcanzable desde otros equipos de tu red. Los secretos reales (credenciales de proveedores externos) nunca llevan valor por defecto ahí — solo el nombre (`security.md` #8).

`make up` genera **dos** claves en tu `.env` local si faltan, y nunca se versionan:

- `JWT_SECRET_KEY` — firma de tokens, `openssl rand -hex 32`.
- `ENCRYPTION_KEY` — cifrado en reposo (Fernet) de las credenciales de PMS. **No tiene la misma forma que la anterior**: Fernet exige base64 de 32 bytes, así que un `rand -hex 32` lo rechaza el validador al arrancar. Se genera con `openssl rand 32 | base64 | tr '+/' '-_' | tr -d '\n'`. El `tr -d` no es opcional: `base64` cierra con salto de línea y sin él salen 45 caracteres, que el validador rechaza al arrancar.

A diferencia de la de firma, la de cifrado **no se regenera sola si ya hay un valor**: cambiarla deja indescifrable todo lo ya cifrado, así que ante una clave con forma incorrecta `make up` para y avisa en lugar de sustituirla.

**El almacén de objetos de las fotos son cinco variables más, y en local se dejan vacías**: `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` y el par `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. Vacías es el caso normal — el MVP local corre con `storage_type = LOCAL` y las fotos van al volumen `backend_media`; que un tenant esté en `S3` significa que sus fotos viven en un bucket del proveedor y que el navegador las lee de ahí por URL prefirmada, sin pasar por el backend. En `dev` el proveedor es OCI Object Storage y Terraform aprovisiona todo; qué vale cada ajuste en OCI, AWS S3, Cloudflare R2 y MinIO está en [`docs/adr/0008-object-storage-provider-dev.md`](docs/adr/0008-object-storage-provider-dev.md).

**La landing pública necesita una variable más, build-time del frontend**: `NEXT_PUBLIC_APP_URL`. Vacía en local y en `.env.example` (es el default — la landing cae a la postura «sin URL pública» y se omite `metadataBase` / `alternates.canonical` / OG `url`); en `dev` el CD la inyecta como build-arg con la URL del tunnel para que el metadata sea indexable. Ver `sdd/specs/app-deploy-dev.md` §Build-args de frontend y `frontend/lib/config/public.ts` para el allowlist que la descarta si trae forma incorrecta.

## Estructura

- `backend/` — FastAPI + Celery (Python, `uv`). Dockerfile en `backend/devops/Dockerfile`. Código de dominio en `backend/app/<dominio>/` con las cuatro capas `domain/` → `application/` → `infrastructure/` → `api/` (regla de dependencia y fontanería en [`docs/adr/0004-backend-layering-pattern.md`](docs/adr/0004-backend-layering-pattern.md) y `sdd/steering/backend-architecture.md`). Son 17 dominios; los que todavía son **solo estructura de datos** —entidades y esquema, sin ningún caso de uso que los use— nacen con `domain/` + `infrastructure/` a secas, y ganan `application/`/`api/` cuando llega el primer caso de uso real: hoy `auth`, `properties`, `reservations`, `integrations`, `tenants`, `cleaning`, `access`, `guests`, `notifications`, `timeline`, `maintenance`, `messaging` y `pricing` son los que tienen las cuatro —`properties` ganó su `api/` con `properties-crud`; `access`, `guests` y `notifications` con `access-notifications`, que trajo la operación de accesos (PRD §15), el registro legal de huéspedes (§17) y la entrega de notificaciones (§14); y `timeline` con `dashboard-api`, que le añadió `application/` y `api/` de golpe: hasta entonces sus eventos los escribían los casos de uso de *otros* dominios y nadie los leía de vuelta (PRD §10). Ese mismo change añade el dominio **`dashboard`** —el decimoséptimo—, que es el lado de lectura del agregado de PRD §9 y el único con `domain/`, `application/` y `api/` pero **sin `infrastructure/` propia**: no tiene tabla ni entidad, compone los puertos de los otros siete dominios. **`maintenance` fue el caso simétrico y ya no lo es**: desde `guest-portal-api` tenía `domain/`, `application/` e `infrastructure/` y **ningún `api/`**, porque su único caso de uso —crear la incidencia que abre el huésped— se exponía por el router del portal. El change `maintenance` le da esa cuarta capa junto con el resto de su flujo: clasificación (automática por job y manual), triaje, aprobación de la propietaria por encima del umbral, asignación con plazo de SLA y el ciclo del técnico hasta el cierre. Son **dos routers y no uno** —`/incidents` y `/owner-approvals`— porque son dos agregados: una incidencia puede levantar dos aprobaciones, la del presupuesto y la del coste real (ver [`docs/maintenance.md`](docs/maintenance.md)). **`messaging` es el caso siguiente**: desde `domain-foundation-ops` tenía `domain/` + `infrastructure/` y ningún escritor, y el change `messaging-ai` le da `application/` y `api/` con la atención de primer nivel al huésped de PRD §13 — detección de idioma, clasificación de intent, seis condiciones de escalación, respuesta desde un catálogo cerrado de plantillas y los siete endpoints de bandeja de PRD §16, bajo un solo router `/conversations` porque `Conversation` es el agregado y un mensaje no tiene identidad fuera de su hilo. Los mensajes entran por el panel o por la API: **no hay ingesta automática desde OTA**, y una conversación de `AIRBNB_MSG`/`BOOKING_MSG` queda muda a propósito hasta que llegue `beds24-messaging-adapter` (ver [`docs/messaging-ai.md`](docs/messaging-ai.md)). **`pricing` es el último en ganar las cuatro capas**: desde `domain-foundation-financial` tenía `domain/` + `infrastructure/` y ningún escritor, y el change `revenue-pricing` le da `application/` y `api/` con el Modo 1 del PRD §19 — la fórmula determinista de PRD §7.17 con sus guardrails, un horizonte de 60 días por vivienda y la aprobación humana de cada precio. **El sistema recomienda y no publica**: quien aprueba sube el precio a la OTA a mano y lo marca `APPLIED_EXTERNAL`. Son **dos routers** —`/pricing-rules` y `/price-recommendations`— porque son dos agregados: la regla que edita una persona y el horizonte que reescribe el job nocturno (ver [`docs/pricing.md`](docs/pricing.md)). El **scheduler** vive en `backend/app/scheduler/` — capa de entrega para el reloj, el equivalente de `api/` para Celery beat: nueve tareas —las cuatro de PRD §8.3 más `dispatch_notifications`, `provision_access_records`, `process_webhook_events` y `classify_incidents`, que el PRD no nombra y declaran como divergencia `access-notifications`, `reservations-webhooks` y `maintenance`, más `generate_price_recommendations`, que **sí** es de PRD §8.3 y es la única que corre a una hora del día (06:00 UTC) en vez de por cadencia—, su calendario y el lock que evita solapes (ver [`docs/celery-jobs.md`](docs/celery-jobs.md)). Comandos operativos en `backend/app/cli/` y `backend/app/integrations/cli/`; adapters de sistemas externos en `backend/app/integrations/`, que además guarda las tablas `webhook_endpoints` y `webhook_events`; migraciones en `backend/alembic/`. Dentro de `integrations` vive también **`app/integrations/infrastructure/storage/`** — el almacenamiento de ficheros, con `LocalFileStorage` (escribe en el volumen `/app/media`) y `S3FileStorage` detrás del mismo puerto, y la factoría que elige uno u otro por el `storage_type` del tenant. Está en `integrations` y no en `cleaning` porque el puerto es compartido, y desde `incident-photos` (2026-08-23) esa razón ya está cobrada: sus llamantes son **dos** —las fotos de limpieza y las fotos de incidencia de `maintenance`—, y `revenue` (`expenses.receipt_storage_key`) sigue nombrado como el siguiente. Junto al almacenamiento vive también la **capa de servido firmado compartida** (`app/integrations/application/signed_serving.py` y `app/integrations/api/signed_media.py`): el cuerpo `403` constante, el `nosniff` y el `Cache-Control` derivado de la firma se escriben una vez y los dos dominios montan su ruta anónima con ella (ver [`docs/cleaning.md`](docs/cleaning.md) y [`docs/maintenance.md`](docs/maintenance.md)). **`backend/scripts/`** queda deliberadamente **fuera de `app/`**: son herramientas de un solo uso contra servicios externos (provisión y sondeo del sandbox de Channex — ver [`docs/channex-staging.md`](docs/channex-staging.md)) o de medición puntual (`measure_tenant_filter.py`) que no deben viajar en el paquete desplegado.
- `frontend/` — Next.js App Router (TypeScript strict, Tailwind, shadcn/ui, TanStack Query, Zustand, react-i18next ES/EN). Application Shell organizado por capas `app/` → `features/` → `components/`·`lib/`. En `app/` vive además la **única pieza de servidor del frontend**: `app/api/[...path]/route.ts`, el proxy same-origin que reenvía `/api/` al backend por la red interna — es lo que hace que el navegador alcance la API sin exponer el backend, y su alcance está fijado por `app/proxy-scope.test.ts` ([`docs/ingress-https.md`](docs/ingress-https.md)). Convenciones detalladas en [`frontend/README.md`](frontend/README.md). Dockerfile en `frontend/devops/Dockerfile`.
- `docker-compose.yml` / `Makefile` — orquestación del stack **local** (build local, hot-reload), en la raíz.
- `docker-compose.worktree.yml` — overlay que **retira la publicación de puertos** en el host. `make up` lo añade solo cuando detecta un worktree enlazado de git **y no se pidió desplazamiento**, para que varios stacks de desarrollo convivan sin chocar. El worktree principal no lo usa y el CD no lo ve nunca.
- `.make/` — **generado y gitignorado**. Ahí escribe `make up PORT_OFFSET=<n>` el overlay con los cuatro mapeos desplazados (`docker-compose.offset.yml`), con números literales y regenerado en cada invocación. Vive fuera de la raíz y **no** se llama `docker-compose.override.yml` a propósito: así Compose no lo descubre por sí solo y el desplazamiento no puede cambiar el veredicto de `make check-compose-ports`.
- `docker-compose.deploy.yml` / `.env.deploy.example` — orquestación del **deploy a dev**: imágenes de GHCR por SHA (sin build), consumido por el CD en la VM.
- `sdd/` — flujo de Spec-Driven Development: specs, changes en curso, steering, roadmap.

Comandos de consola del backend (no hay endpoint para ninguno, a propósito):

- `python -m app.integrations.cli.pms_sync <tenant>` — sincroniza reservas desde el PMS de cada propiedad.
- `python -m app.integrations.cli.pms_credentials set|rotate|show-providers` — guarda y rota las credenciales de proveedor. El secreto se pasa por `PMS_CREDENTIAL_SECRET`, **nunca como argumento**: un argumento queda en el historial del shell y es visible en `ps`. Ver `docs/pms-credentials.md`.
- `python -m app.cli.reset_password --email <dirección>` — rescata una cuenta sin acceso: emite una contraseña temporal, la imprime **una sola vez**, revoca las sesiones y levanta el bloqueo por intentos fallidos. Es la única vía de vuelta del único `TENANT_OWNER` de un tenant, y hoy también la única para cualquiera, porque el correo de recuperación no entrega todavía. **A propósito no tiene objetivo de `make`**: es una operación de rescate, no parte del flujo normal. Ver [`docs/auth-account-recovery.md`](docs/auth-account-recovery.md) y [`RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §8.

## Despliegue a dev (CD)

Push a `main` que toque `backend/**`/`frontend/**` → `.github/workflows/deploy-dev.yml` construye las imágenes `prod` arm64, las publica en GHCR y las despliega en la VM dev (Oracle Cloud) mediante un runner self-hosted que corre en la propia VM (deploy local, sin SSH). Detalle de operación en [`infra/environments/dev/RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §6.

La app desplegada se sirve en **https://autohostai.digitalsec.work**, a través de un Cloudflare Tunnel: `cloudflared` corre en la VM y abre una conexión saliente al edge, que termina TLS y entrega al frontend por una red de compose dedicada al ingress — desde la que **no** se alcanzan `postgres`, `redis` ni `backend`, para que el routing remoto del túnel no pueda publicarlos. **Los puertos 8000 y 3000 ya no están expuestos** — el security list de la VM solo permite SSH (22), y no hay ningún puerto entrante para HTTP/HTTPS. Decisión y alternativas en [`docs/adr/0003-https-ingress-dev.md`](docs/adr/0003-https-ingress-dev.md); operación y diagnóstico en [`RUNBOOK.md`](infra/environments/dev/RUNBOOK.md) §7.
- `docs/` — documentación extendida por capability y diagramas (`docs/diagrams/`: C4, hexagonal, ER, state machine, secuencias).
- `infra/` — IaC por entorno (Terraform), no por dominio de negocio; ver `infra/environments/<entorno>/README.md`.
- `.github/workflows/` — pipelines de CI/CD (GitHub Actions).

## Tests

```bash
docker compose exec backend uv run pytest      # backend, con el stack levantado
docker compose run --rm backend uv run pytest  # backend, con el stack parado (solo en el principal)
cd frontend && npm test                        # frontend, en el host
```

El backend corre **en Docker** y `uv` no está instalado en el host, así que su suite se ejecuta
dentro del contenedor (una versión anterior de este README decía `cd backend && uv run pytest`, que
no funciona en una máquina limpia). El frontend sí se ejecuta en el host, con las dependencias que
`npm install` deja en `frontend/node_modules`.

**En paralelo, si tienes prisa**: `docker compose exec backend uv run pytest -n auto` reparte la
suite entre tantos procesos como núcleos tengas. En una máquina de 12 baja de ~3m a menos de 1m.
Cada worker se lleva su propia base de datos desechable y su propia base lógica de Redis, así que no
se pisan; el tope son 16 workers, que es cuanto Redis sirve por defecto. El comando de arriba —en
serie— sigue siendo el canónico, y es el que conviene con `-k`, porque la salida se lee en orden.

**Desde un worktree enlazado**: la suite habla con `postgres:5432` y `redis:6379` por la red de
compose, que es el camino que ha usado siempre — los puertos del host nunca estuvieron en esa ruta, así
que no publicar no le afecta. La primera forma (`exec`) va siempre: no crea ni recrea nada, se engancha
a los contenedores que ya corren.

La segunda (`run --rm`) **no vale desnuda en un worktree, ni siquiera con el stack levantado**.
Medido, porque la intuición dice lo contrario: Compose recrea una dependencia cuyo hash de
configuración no coincide con la que está corriendo, y un `docker compose` desnudo ahí calcula la del
fichero base —con los cuatro mapeos—, así que recrea `postgres`/`redis` **publicando**. Con el stack
vivo y sin puertos, un `run` desnudo imprime `Recreate` y los deja publicados. Desde un worktree: o
`make up` y `exec`, o `--no-deps` si el comando no toca base de datos, o pasa los dos `-f` a mano.
Mismo criterio, en más detalle, en §«Postura de red del stack local».

El backend tiene **gate de CI en cada PR** (`.github/workflows/backend-tests.yml`):
migraciones Alembic sobre un PostgreSQL limpio, `alembic check`, la suite completa y
`downgrade base`, con Postgres y Redis como services.

La suite tarda ~3 minutos (medido el 2026-08-10), así que **solo se ejecuta cuando el diff
toca `backend/**` o el propio workflow**. El check `backend-tests`, en cambio, **se reporta siempre**: en un PR que
no toca el backend termina en verde en segundos, y el resumen de la ejecución dice
explícitamente que la suite se omitió, para que ese verde no se lea como una suite que pasó.
Un `workflow_dispatch` manual la ejecuta entera en cualquier caso.

Que el check reporte siempre no es un detalle: un filtro de rutas en el disparador `on:`
haría que el workflow no arrancase, y un check requerido que nunca reporta deja el PR
bloqueado para siempre. Por eso la decisión vive dentro de la ejecución y no en `on:`.

Hoy **no está marcado como obligatorio**: el repositorio es privado en un plan sin protección
de rama, así que se ejecuta y reporta pero nada impide fusionar con él en rojo (ver
`sdd/specs/backend-ci.md` §Estado). Cuando pueda marcarse, el contexto a exigir es
`backend-tests` —el job consolidador—, nunca `backend-tests-suite`, que se salta de forma
legítima.

Al abrir la app, el pie muestra la **versión desplegada** (`0.1.0+2026-07-31.5872022`), en el
workspace, las apps de campo y también en `/login` sin sesión — así no hace falta entrar en la
VM para saber qué está corriendo. La versión base vive en `VERSION` (raíz) y el CD la compone
con la fecha de build y el commit corto; el pie muestra esa cadena completa, la misma que
llevan los labels OCI de las imágenes. Cómo se opera:
[`docs/app-version-visibility.md`](docs/app-version-visibility.md).

La API de negocio ya tiene su primera capability: **reservas** (`/api/v1/reservations` más la
importación por CSV `/api/v1/integrations/pms/import-csv`). Se opera por API — el frontend entrega
lista y detalle en modo solo lectura desde `reservations-web` (la escritura `POST`/`PATCH`/`DELETE`
queda fuera de alcance desde la web) — y la sincronización con el PMS se lanza como comando:

```bash
docker compose exec backend uv run python -m app.integrations.cli.pms_sync <tenant-uuid>
```

Roles, formato del CSV, idempotencia y qué queda en el timeline:
[`docs/reservations.md`](docs/reservations.md).

El PMS puede además **avisar** de que una reserva cambió, en vez de esperar al sondeo. El
`TENANT_OWNER` acuña la URL y el secreto de cabecera con `POST /api/v1/integrations/webhook-endpoints`
—se devuelven **una sola vez**— y los pega en el proveedor; el receptor anónimo vive en
`/api/v1/webhooks/{provider}/{token}` y un job de Celery drena la cola cada 60 s. El aviso **nunca es
la fuente de verdad**: ningún proveedor firma sus webhooks, así que lo único que hace es decirnos
dónde mirar y se relee por API. Cómo se opera, cómo se rota y cómo se diagnostica el `404`
deliberadamente indistinguible del receptor:
[`docs/reservations-webhooks.md`](docs/reservations-webhooks.md).

### Verificación del frontend

```bash
cd frontend
npm run dev         # servidor de desarrollo (http://localhost:3000)
npm run typecheck   # TypeScript strict, sin emitir
npm run lint        # ESLint (incluye las fronteras app → features → components/lib)
npm test            # Vitest + Testing Library (jsdom)
npm run test:layout # guarda de desbordamiento a 360px en Chromium — requiere binario, ver abajo
npm run build       # build de producción
npm run test:public-artifacts # escanea .next/static, server/standalone y rutas públicas
npm run test:entrypoint  # test del entrypoint de dev (sincronización de node_modules)
```

`npm test` y `npm run test:layout` son **dos proyectos de Vitest**, no dos formas de correr lo
mismo. El primero es la suite de siempre sobre jsdom, que no hace *layout*: ahí `scrollWidth`
es siempre 0 y una medición de anchos no mediría nada. El segundo abre un Chromium real con
Playwright, renderiza las composiciones del `Topbar` a 360, 420, 520 y 640 px y comprueba que
ninguna desborda horizontalmente; compila antes `app/globals.css` con la CLI de Tailwind, porque
un DOM sin estilos tampoco desborda nunca.

Por eso `test:layout` pide algo que el resto de la suite no: **el binario del navegador**, que se
instala una vez por máquina (y en cada job de CI) con

```bash
cd frontend && npm exec --no -- playwright install --with-deps chromium
```

Sin él, `npm run test:layout` falla al lanzar el navegador. `npm test` no lo necesita y no lo
arrastra.

Es `npm exec --no --` y no `npx` a propósito, y es el mismo comando que corre CI: `npx` se descarga
el paquete del registro cuando no está en `node_modules`, mientras que `--no` usa el binario que
`npm ci` dejó desde el lockfile o falla. En tu portátil la diferencia es que no te instala a la
espalda una versión distinta de la fijada; en CI, donde el manifiesto lo controla el Pull Request y
el paso instala paquetes de sistema, es lo que impide que ese `install` acabe ejecutando código sin
fijar (razonado en `.github/workflows/frontend-tests.yml`).

> Al añadir o actualizar una dependencia del frontend basta con `docker compose up` (o `make up SERVICE=frontend`): el contenedor de dev sincroniza `node_modules` con `package-lock.json` en el arranque, sin `npm install` manual ni reconstruir la imagen.

## Desarrollo con SDD

Este proyecto se desarrolla con **Spec-Driven Development**: cada feature pasa por fases con aprobación humana entre ellas, y el estado completo vive versionado en [`sdd/`](sdd/README.md) — cualquier sesión de agente puede continuar donde lo dejó la anterior.

**Setup (una vez):** los comandos `/sdd:*` los da el plugin [sdd-toolkit](https://github.com/hardcode83/sdd-toolkit) de Claude Code:

```
/plugin marketplace add hardcode83/sdd-toolkit
/plugin install sdd@sdd-toolkit
```

**El ciclo de cada feature:**

| Paso | Comando | Resultado |
|---|---|---|
| 1 | `/sdd:status` | ¿Dónde estamos? Changes activos + roadmap como to-do list |
| 2 | `/sdd:new` | Proposal con requisitos EARS desde la siguiente entrada del roadmap (`sdd/roadmap.md`) — **apruebas tú** |
| 3 | `/sdd:design` | Decisiones técnicas (se salta si el cambio es trivial) — **apruebas tú** |
| 4 | `/sdd:tasks` | Checklist de tareas verificables — **apruebas tú** |
| 5 | `/sdd:run` | Implementa en orden; panel de revisores (architect/security/qa) por sección |
| 6 | `/sdd:archive` | Fusiona en `sdd/specs/`, actualiza README/`docs/`, archiva el change |

**Reglas del repo:**

- Los cambios no triviales entran por `/sdd:new`, nunca directo a código — así `sdd/specs/` sigue siendo la verdad de lo construido.
- Las reglas de arquitectura/seguridad/testing viven en `sdd/steering/` — son vinculantes para agentes (las carga cada fase y las verifica el panel) y para humanos.
- El PRD (`docs/AutoHostAI_PRD_v5_Claude.md`) es la referencia funcional origen; el estado real del sistema son las specs.

Para aprender el flujo completo: [guía paso a paso](https://github.com/hardcode83/sdd-toolkit/blob/main/docs/guide.md) (10 min).
