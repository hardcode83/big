# 0005 — El email como identidad global, no por tenant

## Estado

Aceptado — 2026-07-30. Decidido en la revisión del PR #25 (`auth-tenancy`), a petición de Marta. Se aparta deliberadamente del PRD §7.3.

**Sobre no editar el PRD** (decisión cerrada por Jose el 2026-07-30, antes del merge): el PRD §7.3 sigue diciendo `UNIQUE(tenant_id, email)` y se deja así a propósito. Es el documento funcional de origen y su autoría es de Marta; la verdad de lo construido son las specs (`sdd/README.md`). La desviación queda registrada en este ADR, en el design D16/D19, en `docs/auth-tenancy.md` y en la spec viva que produce el archivado, así que es localizable desde cualquiera de los sitios donde alguien la buscaría. Si Marta prefiere reflejarla también en el PRD, es una edición de una línea sobre su documento y le corresponde a ella.

## Contexto

El PRD §7.3 define la unicidad del email de un usuario como `UNIQUE(tenant_id, email)` (línea 402): la misma dirección puede existir una vez en cada tenant. Es lo razonable si el login lleva un discriminador de tenant —subdominio, campo en el formulario, invitación— porque entonces `{tenant, email, password}` identifica una cuenta.

El login que construye `auth-tenancy` no lo lleva. `POST /auth/login` recibe `{email, password}` y nada más (PRD §23), porque el producto no tiene subdominios por cliente ni alta pública. Con unicidad por tenant, **el email no identifica la cuenta**: la consulta de login es forzosamente global (`find_by_email_globally`, la única query sin scope del sistema, design D16) y puede devolver más de una fila.

La primera versión de este change resolvió esa ambigüedad en el código: proceder solo si hay exactamente una coincidencia, y si hay dos, no autenticar a nadie. Falla cerrado, que es la dirección correcta, pero convierte una colisión en una **denegación de acceso permanente**: quien pueda crear usuarios en el tenant B introduce la dirección del propietario del tenant A y deja fuera esa cuenta, en un producto sin endpoint de desbloqueo ni recuperación (`auth-account-recovery` está marcado opcional en el PRD §24). El único escritor que existía —el bootstrap— se cerró con `BootstrapConflictError`, y la obligación de repetir esa comprobación quedó anotada en la entrada `user-management` del roadmap.

La revisión rechazó ese reparto: dejar el índice por tenant y confiar en que **todo escritor futuro** haga una comprobación global en Python mantiene la invariante expuesta a carreras entre dos altas simultáneas, a scripts de datos, a migraciones y a cualquier adaptador nuevo. Una invariante que decide quién puede entrar en el producto no puede depender de que nadie se olvide.

## Decisión

1. **El email normalizado es único en toda la instalación**, no por tenant.
2. **La garantía está en la base de datos**: índice único funcional `uq_users_lower_email` sobre `lower(email)`. La validación de aplicación deja de ser la garantía y pasa a ser solo un mensaje de error legible.
3. **La comparación es case-insensitive**, y el índice se expresa en los mismos términos que la consulta (`lower(email)`), no en términos que la consulta tenga que respetar por convención.
4. Se **retira** `UNIQUE(tenant_id, email)`. La unicidad global ya la implica, y dos constraints para una sola regla es como acaban divergiendo.
5. Si en el futuro una misma persona necesita pertenecer a varios tenants, se modela con una **identidad global más memberships** separadas, nunca repitiendo la dirección. Queda como criterio de la entrada `saas-cross-tenant` del roadmap.

Implementación: `backend/alembic/versions/e1eed2e039ee_globally_unique_lower_email.py`, `backend/app/auth/infrastructure/models.py`, design D16 y D19.

## Consecuencias

**A favor:**

- El login se simplifica: `find_by_email_globally` devuelve `User | None`, desaparece la regla de "exactamente una coincidencia" y con ella la rama de ambigüedad del caso de uso.
- La obligación heredada que `user-management` tenía que recordar deja de existir: la base de datos rechaza el alta, con o sin comprobación en Python. Lo que le queda a `user-management` es traducir el `IntegrityError` a un 409 con mensaje útil, no sostener la invariante.
- Cierra la variante por mayúsculas del mismo ataque, que un `UNIQUE` case-sensitive dejaba abierta (design D19).
- `scalar_one_or_none` en la consulta de login pasa a ser correcto en lugar de optimista: dos filas ya no son un caso esperado sino una invariante rota, y que reviente es preferible a autenticar la primera que ordene el planificador.

**En contra, y asumido:**

- Una persona no puede tener la misma dirección en dos tenants. Hoy no hay ningún caso de uso que lo pida —los tenants son clientes distintos y los usuarios son sus empleados— y cuando lo haya, el modelo correcto es el punto 5, no repetir el email.
- La migración **falla** si la base de datos ya tiene la misma dirección en dos tenants. En dev solo existen los dos usuarios del bootstrap, verificado antes de aplicarla; para cualquier entorno con datos, el RUNBOOK §6.4 trae la query que localiza los duplicados.
- Es una desviación del PRD. **No se ha editado el PRD**: es el documento funcional de origen y su autoría es de Marta; la desviación se registra aquí, en el design del change y en la spec viva que quede al archivar.

## Alternativas rechazadas

- **Mantener `UNIQUE(tenant_id, email)` y comprobar en Python en cada escritor** — es el reparto que la revisión rechazó: expuesto a carreras, scripts y adaptadores futuros.
- **Añadir un discriminador de tenant al login** (subdominio o campo en el formulario) — resolvería la identidad sin tocar el esquema, pero es un cambio de producto: afecta a la URL del frontend, al flujo de invitación y a la pantalla de login del PRD §24. Demasiado para una revisión de PR, y no lo pide nadie.
- **Índice único sobre `email` sin `lower()`** — más simple, pero deja `Jose@x.com` y `jose@x.com` coexistiendo mientras el login los trata como la misma dirección: el mismo bloqueo con un paso más.
