# BLOCKED — rule11-guard-trigger-and-scope

## 1. El HEAD actual no lo ha visto el panel: falta una pasada para certificar

- **Fase**: review
- **Tipo**: `deferred`
- **Reanudar con**: `/sdd:review rule11-guard-trigger-and-scope` **en sesión nueva** (`/clear` antes)

**Qué falta.** Una pasada del panel sobre `b7773ee` y, si pasa, la secuencia de certificación:
`mark-local-verified` → `mark-ready --base main` → `validate-ship`. Nada más.

**Por qué no está hecho, y por qué en sesión nueva.** El panel pasó siete rondas sobre este change.
Las tres últimas no revisaban el change: revisaban un test que se añadió *durante* la revisión para
anclar la mitad local de R4.1, y que ningún requisito pedía. Ese test se retiró en `b7773ee` con su
motivo escrito en D2 y su hueco convertido en candidato de roadmap, así que **los cuatro FAIL de la
última ronda se resuelven por retirada, no por arreglo** — pero ninguno de los siete revisores ha
leído este SHA, y certificar sobre un commit sin revisar ya salió mal una vez en esta misma sesión
(se hizo, se detectó, y costó deshacerlo con un rebase). La sesión que lo retomó arrastra siete
rondas de contexto que no aportan nada: todo lo que la fase necesita está en disco (regla 11).

**Estado medido de `b7773ee`, para no volver a medirlo:**

| | |
|---|---|
| `make check-rule11-ownership` | salida **0**, 95 markdown + 800 python, cero infractores |
| `pytest scripts/ -q` | **247 passed** (246 de run + el ancla del coste de D3) |
| `make check-compose-ports` · `check-version-parity` | **0** y **0** |
| CI, `Makefile`, `docker-compose.yml`, `scripts/rule11-ownership.py` | idénticos a `9aee60e`, el SHA que el panel de cicd aprobó, salvo el arreglo del numeral obsoleto de la ronda 3 en la guardia |
| Casillas sin marcar en `tasks.md` | **0** |

**Lo que el panel ya estableció y no hace falta re-litigar** (rondas sobre `9b3707b` y anteriores):
`i18n`, `tenancy` y `security` dieron PASS; la guardia falla cerrado por nueve vías verificadas una
a una; el conjunto de coste de D3 está fijado por identidad en cuatro `file:line`; el censo se mide
en 95/800 y el barrido de citas vivas de la ruta vieja deja **dos** líneas de `sdd/roadmap.md` (177 y
219) encargadas a `/sdd:archive` en la tarea 7.7.

**Lo que sigue abierto por diseño**, con destino nombrado y no como deuda oculta: R4.1, la mitad del
check run de R4.2 y R3.1 sobre la base fusionada. Sus seis filas están en el § «Registro de evidencia
sobre la PR» de `tasks.md`, se rellenan tras `/sdd:ship` y se anclan con `mark-recertified`. No son
tareas: son obligaciones declaradas de la capacidad en
`sdd/specs/rule11-ownership-guard.md` § Obligaciones sobre la Pull Request abierta.

**Orden al retomar**: `/sdd:review` (panel sobre `b7773ee`) → certificar → `/sdd:ship` → registrar las
seis filas de evidencia sobre la PR → `/sdd:review` de nuevo, que en `PR_OPEN` recertifica.
