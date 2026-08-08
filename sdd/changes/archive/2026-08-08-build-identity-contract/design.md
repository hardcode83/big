# Design: build-identity-contract

## Context

El job `provenance` de `.github/workflows/deploy-dev.yml` compone hoy `version`,
`commit_short`, `built_at` y `repo_url` con Bash y los publica directamente en
`$GITHUB_OUTPUT`. La frontera pública de `frontend/lib/config/public.ts` valida por separado
`NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT` con dos expresiones regulares;
si el productor cambia de forma, el consumidor falla cerrado y el badge degrada a «versión
desconocida», pero ningún check explica la deriva.

`frontend/lib/config/public.test.tsx` ya caracteriza las formas admitidas y rechazadas, y el
workflow `.github/workflows/frontend-tests.yml` ejecuta `npm test`, lint y typecheck en todos
los Pull Requests sin filtros de paths. `docker-compose.yml` aporta la única identidad local:
`NEXT_PUBLIC_APP_VERSION=local` y commit vacío. No hay scripts compartidos entre GitHub
Actions y el frontend, ni dependencias de runtime que hagan falta para este contrato.

## Decisions

### D1 — Contrato declarativo compartido, con la frontera pública como autoridad semántica

**Chosen:** añadir `frontend/lib/config/build-identity-contract.json` con los patrones y
literales no sensibles que describen la identidad: base `X.Y.Z`, versión canónica de
producción, commit corto de 7 hexadecimales minúsculos y pareja local `local`/vacío.
`frontend/lib/config/public.ts` construirá sus `RegExp` desde ese fichero, añadirá una
comprobación semántica de día válido para combinaciones mes/año y el compositor de CD leerá el
mismo contrato. El JSON preservará exactamente las formas que admite hoy la
frontera —incluida la base `X.Y.Z` sin metadatos que la spec viva mantiene como forma pública
válida—; el CD seguirá emitiendo únicamente la forma canónica completa.

Esto elimina dos copias editables del patrón sin convertir el test en un parser del código de
`buildPublicRuntimeConfig()`. El comportamiento real de esa función seguirá protegido por sus
tests de caracterización y por la prueba de congruencia end-to-end.

Rejected: mantener regex independientes en Bash y TypeScript — recrea la deriva que motiva el
cambio, aunque se añada un test puntual.

Rejected: inspeccionar el texto fuente de `buildPublicRuntimeConfig()` para extraer su regex —
acopla la verificación a detalles de implementación y contradice la obligación contractual de
R2.2.

Rejected: mover la validación pública fuera del frontend — `buildPublicRuntimeConfig()` debe
seguir siendo la frontera que impide que un valor no vetado llegue al payload RSC.

### D2 — Compositor Node sin dependencias y publicación posterior a la validación

**Chosen:** añadir `frontend/scripts/build-identity.mjs`, un módulo ESM ejecutable con el Node
que ya trae `ubuntu-latest`, sin `npm ci` ni paquetes externos. Expondrá funciones puras de
composición y validación para tests, más un adaptador CLI que:

1. lee y recorta `VERSION`;
2. toma una única instantánea UTC para `built_at`;
3. deriva `commit_short` de `GITHUB_SHA` y compone `version`;
4. valida base, timestamp, versión final, commit final y el pareo entre ambos contra el
   contrato compartido;
5. solo después añade, en una única escritura, todos los outputs a `$GITHUB_OUTPUT`.

`.github/workflows/deploy-dev.yml` sustituirá el Bash de composición por esa invocación; los
jobs `build-backend` y `build-frontend` continuarán consumiendo exactamente
`needs.provenance.outputs.{version,commit_short,built_at,repo_url}`. Los mensajes técnicos del
script serán en inglés, conforme a `sdd/project.md`, y nombrarán el componente inválido sin
imprimir valores ajenos a la identidad pública.

Rejected: validar después de escribir cada output — puede dejar un conjunto parcial y no
cumple R1.3/R1.4.

Rejected: conservar la composición inline y llamar después a un validador — mantiene dos
representaciones del productor y permite que una futura edición salte el gate.

Rejected: usar TypeScript con un runner adicional — obliga a instalar dependencias o a usar
soporte experimental solo para componer cuatro strings.

### D3 — Producción estricta, compatibilidad pública intacta

**Chosen:** el compositor solo aceptará una base `X.Y.Z`, un SHA Git completo hexadecimal del
que deriva exactamente 7 caracteres minúsculos y un timestamp UTC canónico. La fecha de la
versión se deriva de ese mismo timestamp, por lo que es una fecha real y no una segunda
lectura del reloj. La versión final debe tener forma `X.Y.Z+YYYY-MM-DD.<7 hex>` y terminar en
el mismo `commit_short` que se publica por separado.

La frontera pública conservará su comportamiento actual: acepta la forma canónica completa,
la base `X.Y.Z` sin metadatos y el literal `local`; el campo `buildCommitShort` acepta solo 7
hexadecimales o queda vacío por ausencia. Este change no añade campos, no amplía patrones y no
cambia la degradación a `""`. La pareja local efectiva seguirá siendo `local`/vacío porque
así la declara `docker-compose.yml` y así se fijará en la prueba de contrato.

Rejected: endurecer ahora `buildPublicRuntimeConfig()` para validar la pareja de campos como
unidad — cambiaría el límite público existente; R1.2 solo exige que el productor CD publique
una pareja congruente.

Rejected: aceptar SHA de 8 o más caracteres, prereleases o timestamps con hora dentro de
`version` — cambia la forma canónica y está fuera de alcance.

### D4 — Prueba de congruencia sobre productor y consumidor reales

**Chosen:** añadir una prueba Vitest de contrato que importe las funciones puras de
`build-identity.mjs`, componga una identidad con base, SHA y tiempo deterministas, la inyecte
en `process.env` y compruebe que `buildPublicRuntimeConfig()` conserva ambos valores. La misma
prueba pasará al validador outputs finales mutados —commit de longitud distinta de 7, fecha no
canónica y base no `X.Y.Z`— y exigirá que los rechace; además conservará los casos negativos
existentes del consumidor para SHA largo, fecha fuera de rango y base no admitida.

La prueba verificará también el punto de integración: `deploy-dev.yml` delega la composición
en `frontend/scripts/build-identity.mjs`, no vuelve a construir `version` o `commit_short`
inline, y sus builds consumen los outputs de `provenance`. Esta aserción de cableado es
deliberadamente pequeña; no intenta interpretar GitHub Actions ni inspeccionar la
implementación interna de la frontera pública.

Rejected: probar solo el JSON — demostraría que el contrato se parsea, no que el productor
real y el consumidor real son congruentes.

Rejected: ejecutar un build Docker para cada caso — es demasiado lento para un contrato puro
y no aporta cobertura sobre la composición.

Rejected: copiar fragmentos del workflow a fixtures de test — una fixture puede permanecer
verde mientras el productor real cambia.

### D5 — El check existente `frontend-tests` es el gate obligatorio de Pull Request

**Chosen:** reutilizar `.github/workflows/frontend-tests.yml`, que ya se crea en todos los
Pull Requests y ejecuta la suite completa sin filtros. La nueva prueba entra en `npm test`; si
falla, el paso consolidado hace fallar el job `frontend-tests`. Así, un PR que afecte al
script productor, al contrato compartido, a `public.ts` o al propio workflow de CD siempre
tiene una verificación de congruencia dentro de sus checks aplicables, sin introducir otra
instalación ni otro nombre de check.

Esta decisión hace obligatorio el resultado dentro del workflow aplicable; no configura
branch protection. Declarar checks requeridos en GitHub sigue perteneciendo a
`infra-github-iac`, como ya documenta el roadmap.

Rejected: crear un workflow nuevo solo para este contrato — duplica checkout/setup/npm para
una prueba que pertenece naturalmente a la suite del consumidor.

Rejected: añadir `pull_request` a `deploy-dev.yml` y condicionar todos sus jobs con `if` —
mezcla el lifecycle de despliegue con validación y aumenta el riesgo de ejecutar por error un
job con permisos de packages o el runner self-hosted desde un PR.

Rejected: confiar solo en que `provenance` falle al hacer push a `main` — descubre la deriva
después del merge y no cumple R2.3.

### D6 — La excepción local se caracteriza, no se reimplementa

**Chosen:** mantener `docker-compose.yml` sin cambios y fijar en la prueba de contrato que sus
defaults siguen siendo `NEXT_PUBLIC_APP_VERSION=local` y
`NEXT_PUBLIC_BUILD_COMMIT_SHORT=""`; la prueba pasará esa pareja por
`buildPublicRuntimeConfig()` y comprobará que se conserva. La comprobación del compose será
una aserción enfocada sobre esos dos defaults versionados, sin levantar servicios ni depender
de `.env`.

Rejected: hacer que Compose lea el JSON contractual — Compose no consume JSON y añadir un
generador para dos defaults empeora la fuente de verdad local.

Rejected: levantar el stack en CI para probar dos interpolaciones — añade puertos, secretos de
desarrollo y tiempo sin aumentar la confianza en el contrato.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Contrato compartido | `frontend/lib/config/build-identity-contract.json` *(nuevo)* | Patrones/literales públicos usados por productor y consumidor |
| Frontera pública | `frontend/lib/config/public.ts` | Sustituir regex literales por regex construidas desde el contrato, sin cambiar el comportamiento |
| Productor CD | `frontend/scripts/build-identity.mjs` *(nuevo)* | Componer, validar y publicar outputs después de validar el conjunto completo |
| Workflow CD | `.github/workflows/deploy-dev.yml` | Delegar el step `provenance` al script; conservar nombres y consumidores de outputs |
| Verificación | `frontend/lib/config/build-identity-contract.test.ts` *(nuevo)*, `frontend/lib/config/public.test.tsx` | Congruencia productor-consumidor, cableado del workflow, defaults locales y casos negativos |
| CI de PR | `.github/workflows/frontend-tests.yml` | Sin cambio previsto: `npm test` ya ejecuta la nueva prueba en todos los PR |
| Compose local | `docker-compose.yml` | Sin cambio previsto: sus dos defaults quedan caracterizados por test |
| Documentación operativa | `docs/app-version-visibility.md`, comentarios de `frontend/lib/config/public.ts` | Sustituir la advertencia «no existe comprobación» por el nuevo gate y su límite |
| Specs vivas | `sdd/specs/app-version-visibility.md`, `sdd/specs/app-deploy-dev.md` | Se actualizarán al archivar, no durante implementación |

## Data & interfaces

**Base de datos y API:** sin cambios; no hay migraciones, endpoints, eventos ni modelos de
dominio nuevos.

**Variables de entorno:** no se añaden. El script consume las variables estándar de GitHub
Actions que ya usa el workflow (`GITHUB_SHA`, `GITHUB_SERVER_URL`, `GITHUB_REPOSITORY` y
`GITHUB_OUTPUT`) y el fichero `VERSION` existente.

**Outputs de `provenance`:** permanecen estables: `version`, `commit_short`, `built_at` y
`repo_url`. `version` sigue siendo `X.Y.Z+YYYY-MM-DD.<7 hex>`; `built_at`, UTC en formato
`YYYY-MM-DDTHH:MM:SSZ`; `repo_url` no entra en el snapshot público.

**Snapshot público:** mantiene exactamente `appVersion` y `buildCommitShort`; no entran SHA
completo, PR, `run_id`, `ref` ni URL del repositorio.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| Extraer la composición cambia accidentalmente un output consumido por los builds | Conservar nombres/formas, probar la función pura y afirmar que ambos builds siguen leyendo `needs.provenance.outputs.*` |
| El contrato JSON amplía o estrecha sin querer la frontera pública | Tests de caracterización existentes más casos positivos/negativos; el cambio inicial debe producir el mismo resultado para todo el corpus actual |
| El workflow vuelve a introducir composición inline y evita el script | Aserción enfocada de cableado contra el fichero real `deploy-dev.yml` dentro del check global de PR |
| El test pasa con una copia del productor en vez del productor real | Importa la misma función que ejecuta el CLI y no usa fixtures del workflow |
| Una escritura parcial deja outputs utilizables tras un fallo | Calcular y validar todo en memoria; una única escritura a `$GITHUB_OUTPUT` al final |
| La prueba local depende del stack o de secretos | Caracterizar los dos defaults versionados sin levantar Compose ni leer `.env` |
| El JSON contractual llega al bundle cliente | Solo contiene patrones y literales ya públicos; ninguna variable, secreto o procedencia adicional se incorpora al snapshot |

## Requirement coverage

| Requirement | Design coverage |
|---|---|
| R1.1 — forma final y fecha UTC válida | D2, D3 |
| R1.2 — versión y commit pareados | D2, D3, D4 |
| R1.3 — fallo antes de outputs/builds | D2 |
| R1.4 — validar valores finales | D2, D4 |
| R2.1 — productor real aceptado por consumidor real | D1, D4 |
| R2.2 — deriva contractual hace fallar | D1, D4 |
| R2.3 — gate aplicable en Pull Request | D5 |
| R2.4 — casos negativos | D3, D4 |
| R3.1/R3.2 — pareja local | D3, D6 |
| R3.3 — degradación pública intacta | D1, D3, D4 |
| R3.4 — sin nueva divulgación | D1, D3 y Data & interfaces |

## Open questions

Ninguna.
