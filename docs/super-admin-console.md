# Consola de plataforma (`SUPER_ADMIN`)

Cómo se opera. El *qué hace* está en las specs EARS de
`sdd/specs/super-admin-console.md` (la pantalla) y `sdd/specs/super-admin-identity.md`
(las tres rutas de backend que consume).

## Entrar

Con un `SUPER_ADMIN` ya sembrado (`app/cli/bootstrap.py`, no hay alta por API), el login
lleva directo a `/platform` — no a `/dashboard`: el rol no pertenece a ningún tenant, así
que no hay `WorkspaceShell` que montar. Cualquier otro rol que pida `/platform` rebota
igual que al resto de superficies protegidas.

## Qué se ve

Una pantalla, una lista: los tenants existentes, más recientes primero, paginados. Sin
buscador ni filtro — si el volumen real lo pide, se añade más tarde.

Dos acciones, ambas abren el mismo panel lateral (`Sheet`), nunca navegan a otra ruta:

- **«New tenant»**, arriba de la lista.
- **«Add staff»**, en cada fila — no solo en el tenant recién creado.

## Crear un tenant

El formulario pide exactamente lo que la API acepta: nombre, email de facturación, país
(código ISO de dos letras), zona horaria e idioma por defecto. Nace `ACTIVE` siempre — no
hay campo de estado que elegir.

Al crearse, el mismo panel ofrece «add staff» sin volver a pedir la lista de tenants —
**la lista no se refresca sola**: el tenant nuevo aparece en su próxima carga natural
(reabrir `/platform`, refoco de pestaña), no al instante. Es una decisión, no un bug: la
alternativa (refrescar la lista tras cada alta) no la pidió el requisito y añadía una
petición de red al camino feliz.

Un nombre que ya use un tenant `ACTIVE` responde `409` y el formulario lo señala en el
campo `name`, con el texto que devuelve la API (en inglés, verbatim — ver «Sobre los
mensajes de error» más abajo).

## Dar de alta al primer personal

Mismo panel, formulario acotado al tenant elegido (el recién creado o cualquier fila de
la lista). Rol restringido a `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER` o
`TECHNICIAN` — `SUPER_ADMIN` nunca aparece en el selector; `GRANTABLE_ROLES` lo sigue
excluyendo y esta pantalla no lo reabre.

La respuesta trae la contraseña temporal **una sola vez**. La pantalla la muestra en un
campo monoespaciado con un botón de copiar y una advertencia fija: no se volverá a
mostrar. Cerrar el panel la descarta sin dejar rastro — no vive en `localStorage`, en la
URL ni en el historial de navegación, y la mutación que la trajo se libera de la caché de
TanStack Query en cuanto el panel se cierra (no espera los cinco minutos por defecto).
Si se pierde, no se recupera desde aquí: la vía es el reset de contraseña que ya describe
[`user-management.md`](user-management.md#cuando-alguien-pierde-su-contraseña), una vez
esa cuenta exista.

## Sobre los mensajes de error

Los dos formularios muestran el mensaje de campo **tal cual lo devuelve el backend**
(`422`/`409`), no un texto localizado inventado — es lo que pidió el requisito
explícitamente. Por eso esos mensajes concretos salen en inglés incluso con la interfaz
en español: son la única excepción a la regla general de i18n de la consola, y está
documentada como tal, no es un descuido. Todo lo demás de la pantalla —encabezados,
botones, estados vacío y de error— sí pasa por `locales/es/platform.json` y
`locales/en/platform.json`.

## Limitaciones asumidas

- **No hay auditoría agregada aquí.** Cada alta ya queda en `audit_logs`
  (`TENANT_CREATED`, `USER_CREATED`), pero leerla de forma consolidada — «todo lo que ha
  hecho este `SUPER_ADMIN`» — es reporting fuera de alcance.
- **No se puede suspender, archivar ni borrar un tenant desde aquí**, ni editar o
  resetear cuentas ya creadas — eso sigue correspondiendo a `saas-cross-tenant`, cuando
  se decida.
- **No hay forma de entrar en un tenant a comprobar que todo va bien** — la ampliación
  que se declaró junto al requisito original queda fuera de esta pantalla, en
  `saas-cross-tenant`.

## Cómo se prueba en local

```bash
make up
make bootstrap          # crea el SUPER_ADMIN seed junto con el tenant inicial
# login con el SUPER_ADMIN sembrado, aterriza en /platform
cd frontend && npx vitest run features/platform
```
