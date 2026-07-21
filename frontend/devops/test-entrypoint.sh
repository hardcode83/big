#!/bin/sh
# Tests del entrypoint de dev (docker-entrypoint.sh) sin red ni cambios en el
# repo: stubbea `npm` y ejecuta el script contra workdirs temporales con
# distintos estados de package-lock.json / node_modules / .lock-hash.
# Correr con: npm run test:entrypoint  (o: sh devops/test-entrypoint.sh)
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRYPOINT="$SCRIPT_DIR/docker-entrypoint.sh"

# npm stub: registra la invocacion y simula que puebla node_modules.
STUB_DIR="$(mktemp -d)"
cat > "$STUB_DIR/npm" <<'STUB'
#!/bin/sh
echo "ci" >> "$NPM_LOG"
mkdir -p node_modules
STUB
chmod +x "$STUB_DIR/npm"

pass=0; fail=0
check() { # $1=descripcion  $2=exit de la condicion (0 = ok)
  if [ "$2" -eq 0 ]; then pass=$((pass + 1)); echo "  ok   - $1";
  else fail=$((fail + 1)); echo "  FAIL - $1"; fi
}

# Ejecuta el entrypoint en $1; deja salida+exit en $OUT/$RC y el log de npm en $NPM_LOG.
run() {
  export NPM_LOG="$1/npm.log"; : > "$NPM_LOG"
  OUT="$(cd "$1" && PATH="$STUB_DIR:$PATH" sh "$ENTRYPOINT" true 2>&1)"; RC=$?
}
npm_called() { [ -s "$NPM_LOG" ]; }

echo "entrypoint sync tests"

# 1) sin node_modules, con lockfile -> instala
w="$(mktemp -d)"; printf 'lock-v1\n' > "$w/package-lock.json"
run "$w"; check "fresh: instala" "$({ [ $RC -eq 0 ] && npm_called; }; echo $?)"

# 2) node_modules sin .lock-hash -> instala
w="$(mktemp -d)"; printf 'lock-v1\n' > "$w/package-lock.json"; mkdir "$w/node_modules"
run "$w"; check "sin hash: instala" "$({ [ $RC -eq 0 ] && npm_called; }; echo $?)"

# 3) hash coincide -> NO instala
w="$(mktemp -d)"; printf 'lock-v1\n' > "$w/package-lock.json"; mkdir "$w/node_modules"
line="$(sha256sum "$w/package-lock.json")"; printf '%s\n' "${line%% *}" > "$w/node_modules/.lock-hash"
run "$w"; check "hash coincide: no instala" "$({ [ $RC -eq 0 ] && ! npm_called; }; echo $?)"

# 4) hash obsoleto -> instala
w="$(mktemp -d)"; printf 'lock-v2\n' > "$w/package-lock.json"; mkdir "$w/node_modules"; printf 'stale\n' > "$w/node_modules/.lock-hash"
run "$w"; check "hash obsoleto: instala" "$({ [ $RC -eq 0 ] && npm_called; }; echo $?)"

# 5) lockfile ausente -> falla ruidoso, no instala (regresion del bug del pipeline)
w="$(mktemp -d)"; mkdir "$w/node_modules"
run "$w"; check "sin lockfile: exit!=0 y no instala" "$({ [ $RC -ne 0 ] && ! npm_called; }; echo $?)"

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
