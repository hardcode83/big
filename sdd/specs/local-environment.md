# Entorno de desarrollo local

## Purpose

Scaffold de monorepo y stack de desarrollo local para AutoHostAI: estructura de repo por componente, orquestación con Docker Compose y un Makefile como único punto de entrada, construidos para ser compatibles con un futuro despliegue remoto sin rehacer imágenes ni estructura.

## Requirements

### Estructura de monorepo por componente

- El repo contiene `backend/` (FastAPI + Celery) y `frontend/` (Next.js App Router), cada uno con su propio `devops/Dockerfile` junto a su código.
- No existe un directorio `/docker` compartido a nivel de raíz: `docker-compose.yml` y `Makefile` orquestan todos los componentes desde la raíz del repo porque necesitan conocerlos a todos a la vez.
- Un componente nuevo sigue la misma convención (directorio propio + `devops/Dockerfile` propio) sin cambiar el layout raíz.

### Stack local vía Docker Compose

- WHEN se ejecuta `docker compose up` (o `make up`) en la raíz, THE SYSTEM SHALL arrancar los servicios `postgres` (postgres:16), `redis` (redis:7), `migrate` (aplica las migraciones Alembic y termina), `backend`, `worker` (Celery, misma imagen que backend), `beat` (el scheduler de Celery, misma imagen y volumen `.venv` propio) y `frontend`.
- `backend`, `worker` y `beat` esperan `condition: service_completed_successfully` de `migrate` antes de arrancar — el esquema de base de datos existe siempre antes de que la app reciba tráfico, sin paso manual (ver spec `domain-foundation-core` para el contenido del esquema).
- WHILE los contenedores `backend`/`frontend` corren en el target `dev`, THE SYSTEM SHALL reflejar cambios de código sin reconstruir la imagen (bind mount del código + volumen nombrado propio por servicio para `.venv`/`node_modules`, para evitar que el bind mount los pise).
- WHEN arranca (o se reinicia) el contenedor `frontend` en target `dev` y el `package-lock.json` difiere de lo instalado en su volumen `node_modules`, THE SYSTEM SHALL instalar las dependencias del lockfile (`npm ci`) antes de ejecutar `next dev` — vía el entrypoint `frontend/devops/docker-entrypoint.sh`, que compara el hash del lockfile con el guardado en `node_modules/.lock-hash`. Añadir o actualizar dependencias del frontend no requiere `npm install` manual ni reconstruir la imagen; evita el `Module not found` clásico por volumen nombrado desactualizado. `node_modules` permanece en `/app` (lo exige el root de compilación de Turbopack).
- WHILE el `package-lock.json` del frontend no cambie entre arranques, THE SYSTEM SHALL NOT reinstalar `node_modules` (arranque rápido), determinándolo por comparación de hash del lockfile.
- IF el `package-lock.json` falta o no es legible en el contenedor `frontend`, THEN THE SYSTEM SHALL abortar el arranque con un error explícito en vez de continuar con dependencias inconsistentes.
- Las dependencias del frontend se instalan siempre con `npm ci` (reproducible a partir del lockfile), tanto al construir la imagen como en la sincronización automática de dev; una desincronización entre `package.json` y `package-lock.json` falla de forma explícita (comportamiento de `npm ci`).
- `backend` y `worker` NUNCA comparten el volumen de `.venv` entre sí (aunque comparten imagen) — hacerlo produce una condición de carrera al arrancar ambos a la vez.
- `postgres` y `redis` declaran `healthcheck`; `backend`/`worker` esperan `condition: service_healthy` de ambos antes de arrancar. `frontend` espera solo a que `backend` haya iniciado (`condition: service_started`).
- IF falta `POSTGRES_DB`, `POSTGRES_USER` o `POSTGRES_PASSWORD` en `.env`, THEN THE SYSTEM SHALL fallar el arranque de `docker compose up` con un mensaje explícito (`${VAR:?mensaje}`) en vez de arrancar mal configurado — defensa en profundidad para quien use `docker compose` directo sin pasar por `make up`.
- IF falta `JWT_SECRET_KEY`, THEN THE SYSTEM SHALL fallar igual, y en los **tres** servicios que importan la configuración al arrancar: `backend`, `worker` y `migrate`. Omitirla en cualquiera de ellos convertiría un despliegue en un fallo de arranque en cadena, porque `backend` y `worker` dependen de que `migrate` termine con éxito.
- `REDIS_URL` (backend/worker), `BACKEND_INTERNAL_URL` (frontend) y `DATABASE_URL` (backend/worker/migrate) están fijados directamente en `docker-compose.yml` vía `environment:` — no vienen de `.env`, porque su valor lo determina la topología de la red de compose, no algo que un desarrollador deba decidir.

### Postura de red del stack local

- THE SYSTEM SHALL publicar `postgres` y `redis` **únicamente en la interfaz de loopback**
  (`127.0.0.1:5432:5432` y `127.0.0.1:6379:6379` en `docker-compose.yml`), de forma que no sean
  alcanzables desde otros equipos de la red a la que esté conectada la máquina.
- WHERE un mapeo se declara sin prefijo de interfaz, Docker publica en `0.0.0.0`; el prefijo
  `127.0.0.1:` es lo único que distingue una cosa de la otra. Acotar a loopback **elimina también
  el binding IPv6**: los servicios acotados no exponen `::`, y los que publican en todas las
  interfaces sí.
- **Por qué no es higiene.** Ese Redis guarda los contadores del límite de intentos de login
  (`login:ip:*`, `login:fail:*`, `login:lock:*`, ver `backend/app/auth/infrastructure/throttle.py`
  y la spec `auth-tenancy`), y corre **sin `requirepass`**. Quien alcance el puerto puede borrarlos
  entre intentos, con lo que el límite de 10 intentos/min por IP y el bloqueo tras 10 fallos que
  exige la regla 7 de `steering/security.md` no se disparan nunca. **La defensa de esos contadores
  en dev local es este bind, no la autenticación de Redis.**
- IF alguna vez se necesita exponer `redis` fuera de loopback, THEN THE SYSTEM SHALL exigir que se
  resuelva antes su autenticación.
- THE SYSTEM SHALL publicar `backend` (`8000`) y `frontend` (`3000`) en **todas** las interfaces, y
  es deliberado: el proyecto es mobile-first y abrir la app desde un móvil real por la IP de LAN es
  cómo se comprueba el diseño en un viewport de verdad. Acotarlos a loopback eliminaría esa vía.
  `worker`, `beat` y `migrate` no publican ningún puerto.
- Consecuencia que conviene no leer de más: **el stack local no es «inalcanzable desde la red»**.
  La UI y la API sí lo son para quien comparta red; lo que no lo es es el acceso directo al
  datastore. Y lo que se cierra es la explotación **desde la red**: con Redis sin `requirepass`,
  otro proceso de la propia máquina sigue pudiendo tocar esos contadores — residual aceptado
  porque es una máquina de desarrollo con datos de prueba.
- WHILE el stack está levantado, THE SYSTEM SHALL seguir permitiendo que los contenedores alcancen
  Postgres y Redis **por nombre de servicio** a través de la red de compose (`postgres:5432`,
  `redis:6379`): el bind acota la publicación en el *host*, no la red interna. Y `localhost:5432` /
  `localhost:6379` siguen sirviendo desde el host, incluida la suite ejecutada fuera de Docker, que
  cae a ese valor por defecto (ver spec `domain-foundation-core`).
- **Esta postura no tiene comprobación automática todavía.** Si alguien publica un puerto sin el
  prefijo, hoy solo lo atrapa la revisión del diff. La guardia que lo comprobaría en cada PR es la
  entrada `compose-ports-guard` del roadmap, separada del change que estableció esta postura
  porque construirla bien resultó tener más fondo del que aparenta — su enunciado lleva el censo de
  vías de elusión ya demostradas.

### Makefile como entrypoint único

- WHEN se ejecuta `make up` y no existe `.env`, THE SYSTEM SHALL crearlo automáticamente copiando `.env.example` antes de levantar el stack — cero pasos manuales para arrancar por primera vez.
- WHEN se ejecuta `make up` y falta `JWT_SECRET_KEY` en `.env` (o está vacía), THE SYSTEM SHALL generarla con `openssl rand -hex 32` bajo `umask 077`, escribirla en el `.env` local y dejar el fichero en `600`, de forma idempotente y también sobre un `.env` preexistente. Es la forma de cumplir a la vez la regla 8 de `steering/security.md` —la clave de firma nunca lleva valor por defecto en el repositorio— y el arranque sin pasos manuales: el valor se genera en la máquina del desarrollador (ver spec `auth-tenancy`).
- WHEN se ejecuta `make up`, `make down`, `make logs`, `make ps` o `make sh`, THE SYSTEM SHALL delegar en el comando `docker compose` equivalente.
- `make bootstrap` crea el tenant y los usuarios iniciales ejecutando `python -m app.cli.bootstrap` dentro del contenedor `backend` — deliberadamente **no** forma parte de `make up`, porque necesita valores que elige una persona (ver spec `auth-tenancy`). Usa `python -m` y no `uv run` para que el mismo comando valga contra la imagen `prod`, que no lleva `uv`.
- `make db-clean-test` borra las bases de datos de test huérfanas que deje una ejecución de pytest interrumpida, sin tocar la de desarrollo (ver spec `backend-ci`).
- WHERE se pasa `SERVICE=<nombre>` a cualquiera de esos targets, THE SYSTEM SHALL limitar la operación a ese servicio — Compose arranca automáticamente sus dependencias declaradas (p.ej. `SERVICE=backend` trae `postgres`+`redis`; `SERVICE=frontend` trae además `backend`).
- `make sh` sin `SERVICE=` abre shell en `backend` por defecto.

### Compatibilidad con despliegue remoto

- Backend lee su configuración exclusivamente vía `Settings(BaseSettings)` (`backend/app/core/config.py`), nunca hardcodeada ni dispersa en `os.getenv`. Frontend lee la suya vía `process.env`.
- Cada `devops/Dockerfile` es multi-stage con targets `dev` (deps de desarrollo, pensado para bind mount) y `prod` (imagen lean, sin deps dev, sin bind mount, ejecutable con el mismo comando fuera de docker-compose).
- `.env.example` (gitignored el propio `.env`, no `.env.example`) trae valores por defecto funcionales para config local sin sensibilidad real (`POSTGRES_*`, `NEXT_PUBLIC_APP_ENV`) — no son secretos, y lo que lo hace aceptable es que `postgres` está publicado **solo en loopback** (ver §Postura de red del stack local), así que ese valor por defecto únicamente es alcanzable desde la propia máquina. La justificación anterior decía «un Postgres solo alcanzable dentro de la red de compose», que era falso mientras el mapeo fue `5432:5432`: sin prefijo de interfaz Docker publica en `0.0.0.0`. Si el mapeo vuelve a publicar fuera de loopback, este default deja de estar justificado (misma condición que la exención de la regla 8 de `steering/security.md`). Los secretos reales siguen la regla de "solo nombre, nunca valor" de `security.md` #8: `JWT_SECRET_KEY` ya está declarada así (nombre, sin valor, generada por `make up`), igual que `CHANNEX_API_KEY` (adapter de validación de Channex, `specs/pms-channex-staging.md`), y las credenciales futuras de WhatsApp/SES.Hospedajes y `ENCRYPTION_KEY` harán lo mismo. `CHANNEX_BASE_URL` es la excepción deliberada: **lleva valor**, comentado como los demás overrides opcionales, porque no es un secreto y ese default apuntando a staging es lo que impide que un descuido de configuración escriba en una cuenta de proveedor viva.
- `.gitignore` excluye `.env*` con excepciones explícitas para `.env.example` y `.env.deploy.example` — un `.env.local` o `.env.deploy` con valores reales no puede colarse por olvido.

### Esqueleto ejecutable mínimo

- El backend expone `GET /health` → `200 {"status": "ok"}`.
- El frontend renderiza dinámicamente (sin cachear el resultado en build time) una página raíz que hace fetch a `${BACKEND_INTERNAL_URL}/health` y muestra `backend: ok` o `backend: ko` según la respuesta.
- El worker ejecuta las cuatro tareas periódicas de PRD §8.3 que `celery-jobs` registra en `backend/app/worker.py`, con broker/backend en `REDIS_URL`; `beat` es quien las dispara (ver `specs/celery-jobs.md`). El fichero de estado de `beat` aparece como `backend/celerybeat-schedule` en el árbol de trabajo —el bind mount de `./backend` lo hace persistente en el host, no efímero— y está en `.gitignore`.

### Inicialización de git

- El repo tiene un `.git` inicializado en la rama `main`.
- `.gitignore` excluye `.env`, `node_modules/`, `__pycache__/`, `.venv/`, `.next/`, `dist/`, `build/` y artefactos de editor/OS — ninguno de ellos está trackeado.

## Key files

- Raíz: `docker-compose.yml`, `Makefile`, `.env.example`, `.gitignore`, `README.md`.
- Backend: `backend/devops/Dockerfile`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/worker.py`, `backend/pyproject.toml` + `backend/uv.lock`, `backend/tests/test_health.py`.
- Frontend: `frontend/devops/Dockerfile`, `frontend/devops/docker-entrypoint.sh` (sincroniza `node_modules` con el lockfile en dev), `frontend/devops/test-entrypoint.sh` (test del entrypoint, `npm run test:entrypoint`), `frontend/app/(workspace)/page.tsx` (redirige `/` a `/dashboard`), `frontend/app/layout.tsx`, `frontend/next.config.ts`, `frontend/app/route-wiring.test.tsx` (verifica el wiring de la ruta raíz).
