#!/bin/sh
set -e

# Mantiene node_modules (volumen persistente) sincronizado con el lockfile de
# forma automatica en cada arranque del contenedor de dev. Solo reinstala si el
# package-lock.json cambio respecto a lo ya instalado, comparando su hash.
#
# Esto evita el problema clasico del volumen nombrado que queda desactualizado:
# al anadir/actualizar dependencias basta con "docker compose up" (o restart);
# no hace falta "npm install" manual ni reconstruir la imagen.

LOCK_FILE="package-lock.json"
HASH_FILE="node_modules/.lock-hash"

# El lockfile es obligatorio: si falta o no es legible, fallar de forma ruidosa
# en vez de asumir "al dia" (evita el estado inconsistente descrito en design.md).
if [ ! -r "$LOCK_FILE" ]; then
  echo "[entrypoint] ERROR: $LOCK_FILE no existe o no es legible" >&2
  exit 1
fi

# Sin pipeline "| cut": capturamos la salida de sha256sum (su fallo propaga por
# set -e) y recortamos el hash con expansion de parametros. Un pipeline
# enmascararia un fallo de sha256sum tras el exito de cut.
current_line="$(sha256sum "$LOCK_FILE")"
current_hash="${current_line%% *}"
installed_hash="$(cat "$HASH_FILE" 2>/dev/null || echo "")"

if [ ! -d node_modules ] || [ "$current_hash" != "$installed_hash" ]; then
  echo "[entrypoint] Dependencias desactualizadas o ausentes -> npm ci"
  npm ci
  echo "$current_hash" > "$HASH_FILE"
else
  echo "[entrypoint] Dependencias al dia (lockfile sin cambios)"
fi

exec "$@"
