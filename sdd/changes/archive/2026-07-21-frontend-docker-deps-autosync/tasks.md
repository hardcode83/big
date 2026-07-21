# Tasks: frontend-docker-deps-autosync

> Implementación ya realizada y verificada durante la sesión del fix; las tareas
> se marcan `[x] (preexistente)` tras comprobarse contra el código real.

## 1. Instalación determinista + entrypoint de sincronización (stage dev) <!-- panel: PASS 2026-07-21 -->


- [x] 1.1 `npm install` → `npm ci` en la etapa `deps` y guardar el hash del lockfile tras instalar — `frontend/devops/Dockerfile` (`RUN npm ci && sha256sum package-lock.json | cut -d' ' -f1 > node_modules/.lock-hash`) [R2] _(preexistente)_
- [x] 1.2 Crear el script que sincroniza `node_modules` con el lockfile por hash (`npm ci` solo si difiere; `set -e`; falla ruidoso si el lockfile falta/no es legible; sin pipeline `| cut` para no enmascarar fallos de `sha256sum`) — `frontend/devops/docker-entrypoint.sh` (nuevo) [R1, R3] _(preexistente + hardening panel QA)_
- [x] 1.3 Cablear el entrypoint solo en el stage `dev` (`COPY` + `chmod +x` + `ENTRYPOINT`), dejando `CMD ["npm","run","dev"]` — `frontend/devops/Dockerfile` [R1] _(preexistente)_
- [x] 1.4 Confirmar que el stage `prod` queda intacto (sin `ENTRYPOINT`, sigue en `CMD ["node","server.js"]`) — `frontend/devops/Dockerfile` [R2] _(preexistente — verificado por inspección)_

## 2. Verificación <!-- panel: PASS 2026-07-21 -->

- [x] 2.1 Build + arranque limpios (volumen recreado): `docker compose build frontend` y `docker compose up -d frontend`; el frontend responde HTTP 200 y **no** aparece `Module not found: Can't resolve '@radix-ui/react-dialog'` en logs [R1] _(preexistente — verificado: status 200, logs sin errores de módulo)_
- [x] 2.2 Sincronización automática: invalidar el marcador (`node_modules/.lock-hash`) y `docker compose restart frontend` → el entrypoint ejecuta `npm ci` y la app vuelve a 200 [R1, R3] _(preexistente — verificado: log `[entrypoint] Dependencias desactualizadas … -> npm ci`, status 200)_
- [x] 2.3 Sin coste cuando no hay cambios: en un arranque sin cambios de lockfile el entrypoint registra `Dependencias al dia (lockfile sin cambios)` y no reinstala [R3] _(preexistente — verificado en el primer arranque)_
- [x] 2.4 Regresión: la suite de tests del frontend sigue pasando — `docker compose exec frontend npm test` [R1] _(verificado: 33 archivos / 149 tests OK)_
- [x] 2.5 Test automatizado del entrypoint (5 estados: fresh / sin hash / hash coincide / hash obsoleto / lockfile ausente) — `frontend/devops/test-entrypoint.sh` + script `test:entrypoint` en `package.json` — `docker compose exec frontend npm run test:entrypoint` [R1, R3] _(verificado: pass=5 fail=0)_
