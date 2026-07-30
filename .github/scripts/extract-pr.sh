#!/usr/bin/env sh
# Extrae el número de Pull Request del subject de un commit.
#
# Vive en un script, y no embebido en deploy-dev.yml, para que la lógica del pareo
# pantalla↔PR tenga test de regresión: `--self-test` es lo que invoca el gate de CI
# (hallazgo del panel de QA en la sección 3 del change app-version-visibility). Sin esto,
# aflojar el ancla del `sed` reintroduciría en silencio el falso positivo de leer un número
# de ISSUE como número de PR, y ningún gate lo vería.
#
# Uso:
#   extract-pr.sh "<subject>"   → imprime el número, o nada si no hay PR
#   extract-pr.sh --self-test   → ejecuta la tabla de casos y falla si alguno no cuadra
#
# Solo se aceptan las DOS formas canónicas, ancladas (design D3):
#   "Merge pull request #N from ..."  → merge commit, la estrategia de este repo
#   "título (#N)"                     → squash, si algún día se cambia
# Cualquier otra mención de "#N" se ignora a propósito: "fix: cierra #7" habla de un ISSUE,
# y enlazar al sitio equivocado es peor que no enlazar (R1.6/R1.7).

set -eu

extract_pr() {
    pr="$(printf '%s' "$1" | sed -n 's/^Merge pull request #\([0-9]\{1,\}\) .*/\1/p')"
    if [ -z "$pr" ]; then
        pr="$(printf '%s' "$1" | sed -n 's/.*(#\([0-9]\{1,\}\))$/\1/p')"
    fi
    printf '%s' "$pr"
}

self_test() {
    failures=0
    # Cada caso es "subject|esperado". El esperado vacío significa "sin PR".
    while IFS='|' read -r subject expected; do
        [ -n "$subject" ] || continue
        actual="$(extract_pr "$subject")"
        if [ "$actual" = "$expected" ]; then
            printf '  ok    %-58s → %s\n' "$(printf '%.56s' "$subject")" "${actual:-<sin PR>}"
        else
            printf '  FALLO %-58s → esperado "%s", obtenido "%s"\n' \
                "$(printf '%.56s' "$subject")" "$expected" "$actual"
            failures=$((failures + 1))
        fi
    done <<'CASES'
Merge pull request #24 from autohostai-labs/sdd/ingress-https-dev|24
Merge pull request #1 from x/y|1
Merge pull request #1234567 from x/y|1234567
squash con título (#42)|42
revert (#99)|99
fix: cierra #7 y #9|
fix: cierra #7|
sdd(archive): algo sin PR|
Merge branch 'main' into sdd/x|
Merge remote-tracking branch 'origin/main' into sdd/x|
Merge pull request #24|
habla de (#42) pero no al final|
texto con $(id) y `backticks` y "comillas"|
Merge pull request #abc from x/y|
CASES

    if [ "$failures" -ne 0 ]; then
        printf '✗ %s caso(s) de extracción de PR no cuadran\n' "$failures"
        exit 1
    fi
    printf '✓ extracción de PR: todos los casos correctos\n'
}

if [ "${1:-}" = "--self-test" ]; then
    self_test
else
    extract_pr "${1:-}"
fi
