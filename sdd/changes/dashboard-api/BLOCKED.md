# BLOCKED — dashboard-api

Cola abierta por `/sdd:review` del 2026-08-09. De las cuatro entradas iniciales quedan **una**;
las otras tres se resolvieron en la ronda de arreglos del mismo día y están descritas en el
mensaje del commit de la feature. Resolver esta entrada borra el fichero.

---

## 1. La rama está 11 commits por detrás de `main`, con conflicto garantizado

- **Fase**: review
- **Tipo**: deferred
- **Qué y por qué**: `sdd/dashboard-api` no ha integrado `main`, que entretanto mergeó el PR
  #73 (`cleaning-photos-storage`). Dos consecuencias objetivas:
  1. **`README.md` tiene conflicto textual garantizado**: ambas ramas reescriben la *misma*
     línea (el bullet de `backend/`), ésta a «Son 17 dominios…» y `main` conservando «Son 16
     dominios…» más un párrafo de rutas de almacenamiento. Los dos hechos tienen que
     sobrevivir a la resolución.
  2. **Los dos artefactos de contrato no se pueden mergear con git**: `backend/openapi.json`
     (`sort_keys=True`) y `frontend/lib/api/generated/openapi.d.ts` (`alphabetize: true`) se
     han regenerado *independientemente* en ambas ramas. `api-contract.yml:85` y
     `frontend-api-contract.yml:41` comparan el fichero commiteado contra una regeneración
     desde el código **mergeado**, no contra lo que produzca el merge línea a línea de git:
     un merge sin conflictos aun así pondría la CI en rojo. Hay que **regenerarlos después**
     de integrar `main`.
  Otros seis ficheros compartidos (`backend/app/cleaning/{domain/repositories,domain/value_objects,infrastructure/repositories}.py`,
  `backend/app/main.py`, `backend/tests/test_openapi_contract.py`,
  `backend/tests/test_route_authorization.py`) insertan en anclas distintas y muy
  probablemente automergean, pero conviene resolverlos aquí y no en el merge del PR.
- **Comando de reanudación**: integrar `main` en `sdd/dashboard-api`, resolver `README.md` a
  mano, regenerar los dos artefactos de contrato (`make openapi` y el workaround de
  `sdd/project.md` § Worktree bootstrap para `api:generate`), volver a correr la suite
  completa, y después `/sdd:review dashboard-api`.
