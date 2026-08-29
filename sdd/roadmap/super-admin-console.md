# super-admin-console

[BE+FE] **la consola de plataforma del `SUPER_ADMIN`: el rol existe, no alcanza ninguna pantalla, y el alta
de tenants y de personal se hace hoy a mano contra la base de datos.**

**Lo que Jose declaró el 2026-08-29**, en el gate de `/sdd:design` de `notifications-inbox-web`, y que es el
requisito de producto de esta entrada:

- `SUPER_ADMIN` es un superusuario **con visibilidad sobre todos los tenants y no perteneciente a ninguno**.
- Su menú en el frontend tiene que hacer lo que hoy se hace escribiendo en la base de datos o llamando a la
  API a mano: **crear tenants, managers, cleaners y technicians**.
- Ampliación prevista y **no comprometida**: entrar en un tenant a comprobar que todo va bien.
- Motivo declarado el 2026-08-29 al pedir la entrada: *sin esto una correcta gestión de la plataforma es
  imposible*. Queda registrado como lo que es —una declaración de necesidad operativa, no una prioridad
  derivada del roadmap—, para que quien la recoja sepa que no es un «algún día».

**Censo de permisos medido el 2026-08-29** (obligatorio antes de convertir esto en proposal: es una entrada
con mitad `[FE]`, y el precedente de `cleaner-app` y `tech-app` es que una entrada de pantalla cuyo rol no
puede llamar lo que la pantalla muestra **no es implementable**). Seis hallazgos, y cuatro de ellos son
bloqueantes por separado:

1. `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` es `_SELF_SERVICE` y nada más: `READ_OWN_PROFILE`,
   `MANAGE_OWN_SESSION`, `READ_OWN_NOTIFICATIONS`. `policy.py` lo argumenta por escrito y **a propósito**:
   sus poderes de PRD §6 son globales —tenants, configuración global, integraciones—, no la operación de un
   tenant, y concederle permisos operativos ahí *"would pre-empt that decision"* de `saas-cross-tenant`.
2. **No alcanza ninguna superficie autenticada.** `ROLE_HOME` (`frontend/features/auth/lib/role-home.ts`)
   tiene cuatro filas y ninguna es la suya, así que `roleHome` cae a `/dashboard`; y
   `frontend/app/(workspace)/layout.tsx` monta `AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}`,
   que lo rebota. `/welcome` solo contempla `CLEANER` y `TECHNICIAN`.
3. **`POST /api/v1/tenants` no existe.** El router de tenants tiene exactamente `GET /{tenant_id}` y
   `PATCH /{tenant_id}`. El **único** creador de tenants de todo el backend es `app/cli/bootstrap.py:129`,
   un comando de CLI. Crear un tenant desde una pantalla es una ruta nueva, no una pantalla nueva.
4. **`GRANTABLE_ROLES = frozenset(UserRole) - {UserRole.SUPER_ADMIN}`** (`auth/domain/entities.py:14`), y lo
   hacen cumplir tanto `User.create` como el cambio de rol. Es decir: **no se puede crear ni promover a un
   `SUPER_ADMIN` por API**; solo existe el que siembra el bootstrap. Si la consola tiene que dar de alta a
   otro administrador de plataforma, eso es una excepción explícita a esa regla y hay que decidirla.
5. **`users.tenant_id` es `NOT NULL`** (migración baseline) y `UserModel` lleva `TenantScopedMixin`. Un
   `SUPER_ADMIN` «no perteneciente a ningún tenant» **no cabe en el esquema de hoy**: es una migración más
   una excepción a la regla 1 de `steering/security.md` —`tenant_id` siempre del token, sin bypass— que
   `auth-tenancy` fijó absoluta y verificable con tests **a propósito**.
6. `POST /api/v1/users` exige `MANAGE_USERS`, que `SUPER_ADMIN` no tiene, y **deriva el tenant del token**,
   así que aunque se le concediera crearía usuarios en su propio tenant y no en el que le interese.

**La frontera con `saas-cross-tenant`, que es lo que impide volver a confundirlas**: aquella entrada es
*post-MVP y condicional*, y cubre **leer datos operativos de otros tenants e impersonar con auditoría**.
Esta cubre **administrar la plataforma**: crear el tenant y sus cuentas. No es lo mismo y la excepción a la
regla 1 que necesita es más estrecha —escritura de tenants nuevos y de usuarios en un tenant nombrado, no
lectura transversal del dominio—, que es justamente por lo que se separan y por lo que ésta **no depende**
de aquélla. La ampliación de «entrar en un tenant» **es** la impersonation de `saas-cross-tenant` y queda
**fuera de alcance** aquí: cuando llegue, llega por allí.

**Aviso de dimensión, del precedente exacto**: el `/sdd:new` de `tech-app` se abrió y se cerró **sin
proposal** el 2026-08-19 porque de las once cosas que PRD §12 pedía solo cuatro tenían backend, y de ahí
salieron tres entradas `[BE]`. Aquí el censo de arriba dice lo mismo con más fuerza —la mitad de pantalla no
tiene detrás ni ruta de alta de tenant, ni permiso, ni esquema que admita un usuario sin tenant—, así que lo
esperable es que su `/sdd:new` la parta. Los cortes naturales, para no derivarlos otra vez:
**(a)** el modelo de identidad del `SUPER_ADMIN` (tenant nulo o tenant de plataforma, y la excepción a la
regla 1 documentada en el steering); **(b)** las rutas de administración de plataforma (`POST /tenants` y el
alta de usuarios en un tenant nombrado, con su auditoría); **(c)** la consola de frontend, que solo entonces
es implementable.

**Nota de método**: ADR 0005 dejó el email único en toda la instalación, y `saas-cross-tenant` ya apuntó que
una persona en varios tenants se resuelve con **identidad global más memberships** y nunca repitiendo el
email. El corte (a) de arriba es el primero que toca ese terreno, así que conviene leer esa nota antes de
decidir, no después.
