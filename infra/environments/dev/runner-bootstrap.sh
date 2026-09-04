#!/usr/bin/env bash
# Bootstrap del POOL de runners self-hosted de GitHub Actions (label = $ENV) en la VM.
# Crea N agentes en la misma VM: un usuario Linux por agente (`actions-runner-<i>`),
# su `actions-runner-<i>/` propio, su servicio systemd y su registro ante GitHub con
# label $ENV. Idempotente en el alta (`--replace`); la baja es EXPLÍCITA cuando
# `RUNNER_COUNT` baja (fase previa al bucle) y está condicionada a `systemctl is-active`.
#
# Parámetros:
#   $1 — RUNNER_COUNT (entero 1..4). Default: $RUNNER_COUNT si está exportado, si no 4
#         (**amend 2026-09-04**: el default era 2; subido a 4 para alinear con
#         `variables.tf` `runner_count` default).
#         El cloud-init pasa siempre "$RUNNER_COUNT" (variables.tf `runner_count`, 1..4,
#         default 4 — change ci-runner-pool-oci, R1/R6); el reaprovisionamiento a mano
#         (RUNBOOK §6.2) también lo pasa o hereda $RUNNER_COUNT del entorno.
#
# Registro vía GitHub App: lee la clave privada de la App del OCI Vault por INSTANCE PRINCIPAL,
# mintea un installation-token (helper gh-app-install-token.py) y con él pide el registration-token.
# El installation-token va por --config/stdin (fuera de argv). El registration-token, en cambio,
# se pasa a `config.sh --token` por argv — inevitable; mitigado: es efímero, de un solo uso y se
# consume con --replace. Idempotente. Un installation-token sirve para los N registros (D5).
#
# Source of truth de los agentes numerados: `/var/lib/autohostai-runner/agents.list`
# (un nombre por línea). El agente legado `autohostai-${ENV}-vm` (sin sufijo numérico)
# es detectado por `GET /repos/{owner}/{repo}/actions/runners` antes del bucle y
# retirado explícitamente — sin esa migración, una VM provisionada por `ci-runner-oci`
# y re-aprovisionada con N>1 deja agentes de más (D3 / R5.2).
set -euo pipefail

umask 077

# shellcheck disable=SC1091
source /etc/autohostai-deploy.env # ENV, GITHUB_REPO, GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, APP_KEY_SECRET_OCID, ...

# RUNNER_COUNT: argumento posicional (cloud-init / reaprovisionamiento explícito) > variable
# de entorno > default 4 (alineado con `variables.tf` `runner_count` default — amend 2026-09-04).
if [[ -n "${1:-}" ]]; then
    RUNNER_COUNT="$1"
elif [[ -z "${RUNNER_COUNT:-}" ]]; then
    RUNNER_COUNT=4
fi
if ! [[ "$RUNNER_COUNT" =~ ^[1-4]$ ]]; then
    echo "ERROR: RUNNER_COUNT=$RUNNER_COUNT fuera de rango (1..4)" >&2
    exit 1
fi

# Constantes derivadas — un prefijo de servicio por agente, y la lista de verdad en disco.
AGENTS_DIR=/var/lib/autohostai-runner
AGENTS_LIST="$AGENTS_DIR/agents.list"
ORG_REPO_DASHED="${GITHUB_REPO//\//-}"                 # autohostai-labs-AutoHostAI
SERVICE_PREFIX="actions.runner.${ORG_REPO_DASHED}.autohostai-${ENV}-vm"
LEGACY_NAME="autohostai-${ENV}-vm"
LEGACY_SERVICE="actions.runner.${ORG_REPO_DASHED}.${LEGACY_NAME}.service"
LEGACY_HOME="/opt/actions-runner"

mkdir -p "$AGENTS_DIR"
# Grupo docker: cloud-init lo crea; reasegurar para el alta out-of-band.
getent group docker >/dev/null || groupadd docker

# === 1) Installation-token de la GitHub App (clave del Vault → helper). Un token sirve para
#       los N registros (D5). Vive solo en memoria: umask 077 arriba, `unset` al final.
#       GITHUB_APP_ID/INSTALLATION_ID se pasan explícitos al helper: `source` sin `export` no
#       los propaga al subproceso python (mismo patrón que el deploy).
INSTALL_TOKEN="$(oci --auth instance_principal secrets secret-bundle get \
    --secret-id "$APP_KEY_SECRET_OCID" \
    --query 'data."secret-bundle-content".content' --raw-output \
    | base64 -d \
    | GITHUB_APP_ID="$GITHUB_APP_ID" GITHUB_APP_INSTALLATION_ID="$GITHUB_APP_INSTALLATION_ID" \
        python3 /opt/gh-app-install-token.py)"

export INSTALL_TOKEN GITHUB_REPO   # los helpers de abajo los leen del entorno

# === 2) Registration-token del repo. Va por --config desde STDIN (no en argv → no aparece
#       en /proc/<pid>/cmdline). El registration-token también vale para `config.sh remove`.
REG_TOKEN="$(printf 'header = "Authorization: Bearer %s"\n' "$INSTALL_TOKEN" \
    | curl -fsSL -X POST --config - \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$GITHUB_REPO/actions/runners/registration-token" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"

# === 3) Helpers GitHub ===

# Lista los nombres de corredores del repo (uno por línea). Falla con `set -e` si la API rechaza.
# INSTALL_TOKEN viaja por `--config -` (stdin) para no aparecer en `argv` (ni en /proc/<pid>/cmdline),
# mismo patrón que `REG_TOKEN` arriba.
gh_list_runner_names() {
    printf 'header = "Authorization: Bearer %s"\n' "$INSTALL_TOKEN" \
    | curl -fsSL --config - \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$GITHUB_REPO/actions/runners?per_page=100" \
        | python3 -c 'import sys,json
data = json.load(sys.stdin)
for r in data.get("runners", []):
    print(r.get("name", ""))'
}

# URL del primer run IN_PROGRESS que tenga un job corriendo en `target` (runner.name).
# Vacío si no hay ninguno (sale 0 sin imprimir nada). Si la API rechaza, imprime error y sale !=0.
gh_in_progress_url_for_runner() {
    local target="$1"
    INSTALL_TOKEN="$INSTALL_TOKEN" GITHUB_REPO="$GITHUB_REPO" \
        python3 - "$target" <<'PY'
import json, os, sys, urllib.request, urllib.error
target = sys.argv[1]
token = os.environ["INSTALL_TOKEN"]
repo = os.environ["GITHUB_REPO"]

def gh_get(url):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

try:
    runs = gh_get(f"https://api.github.com/repos/{repo}/actions/runs?status=in_progress&per_page=100").get("workflow_runs", [])
except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
    sys.exit(1)  # API rechazó: que `set -e` aborte y el operador vea el error

for r in runs:
    rid = r.get("id")
    if not rid:
        continue
    try:
        jobs = gh_get(f"https://api.github.com/repos/{repo}/actions/runs/{rid}/jobs?per_page=100").get("jobs", [])
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        continue
    for j in jobs:
        if j.get("status") == "in_progress" and j.get("runner_name") == target:
            print(r.get("html_url", ""))
            sys.exit(0)
PY
}

# === 4) Helper: retirar un agente NUMERADO (`autohostai-${ENV}-vm-<i>`).
#       Asume `set -e` activo: cualquier paso que falle aborta el script.
retire_named_agent() {
    local name="$1"
    if ! [[ "$name" =~ ^autohostai-${ENV}-vm-([0-9]+)$ ]]; then
        echo "ERROR: nombre de agente numerado $name no encaja con el patrón esperado" >&2
        return 1
    fi
    local i="${BASH_REMATCH[1]}"
    local home="/opt/actions-runner-${i}"
    local svc="${SERVICE_PREFIX}-${i}.service"
    if [[ -d "$home" ]]; then
        cd "$home"
        sudo -u "actions-runner-${i}" ./config.sh remove --token "$REG_TOKEN"
        ./svc.sh uninstall "$svc"
    else
        echo "WARN: home $home ausente, saltando config.sh remove para $name" >&2
    fi
}

# === 5) Helper: instalar/registrar un agente NUMERADO en una subshell con `set -e` aislado.
#       Devuelve 0 si OK; cualquier fallo imprime "agent <i>/<N>: <step>: failed" y devuelve !=0.
#       El step concreto lo captura un trap ERR contra la variable `step` (vía función para
#       que se evalúe al FALLAR, no al instalar el trap — un `'...$step...'` en single-quotes
#       capturaría el valor vacío de `step` y diría "agent k/N: failed" sin contexto).
install_named_agent() {
    local i="$1"
    local runner_user="actions-runner-${i}"
    local runner_home="/opt/actions-runner-${i}"
    local agent_name="autohostai-${ENV}-vm-${i}"
    local svc="${SERVICE_PREFIX}-${i}.service"
    local step=""
    (
        set -euo pipefail
        # on_err se invoca cuando cualquier comando subsecuente sale !=0: imprime el step
        # ACTUAL (no el de cuando se instaló el trap — por eso es función y no string).
        on_err() {
            echo "agent ${i}/${RUNNER_COUNT}: ${step} failed" >&2
            exit 1
        }
        trap on_err ERR

        step="ensure user $runner_user"
        if ! id "$runner_user" >/dev/null 2>&1; then
            useradd -m -s /bin/bash "$runner_user"
        fi
        usermod -aG docker "$runner_user"

        step="install runner into $runner_home"
        mkdir -p "$runner_home"
        cd "$runner_home"
        if [[ ! -x ./config.sh ]]; then
            runner_version="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
                | python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
            curl -fsSL -o runner.tar.gz \
                "https://github.com/actions/runner/releases/download/v${runner_version}/actions-runner-linux-arm64-${runner_version}.tar.gz"
            tar xzf runner.tar.gz && rm -f runner.tar.gz
        fi
        chown -R "${runner_user}:${runner_user}" "$runner_home"

        step="config.sh register $agent_name"
        sudo -u "$runner_user" ./config.sh \
            --url "https://github.com/$GITHUB_REPO" \
            --token "$REG_TOKEN" \
            --labels "$ENV" \
            --name "$agent_name" \
            --unattended --replace

        step="svc.sh install/start $svc"
        state="$(systemctl is-active "$svc" 2>&1 || true)"
        case "$state" in
            active) ;;  # ya activo: no tocar (un servicio parado pero presente se reinicia abajo)
            failed|inactive|unknown)
                ./svc.sh install "$runner_user"
                ./svc.sh start
                ;;
            *)
                echo "agent $i/$RUNNER_COUNT: estado inesperado '$state' para $svc" >&2
                exit 1
                ;;
        esac
    )
}

# === 6) FASE 0 — migración del agente legado.
#       Si GitHub lista un agente con nombre `autohostai-${ENV}-vm` (sin sufijo numérico), se
#       retira. Si no, no-op. El `agents.list` no contiene al legado: la fase de baja mira
#       GitHub directamente para esta migración (one-shot — el legado nunca reaparece una vez
#       retirado porque el bucle solo registra nombres numerados).
echo "[bootstrap] RUNNER_COUNT=$RUNNER_COUNT, ENV=$ENV"
legacy_listed="$(gh_list_runner_names)"
if printf '%s\n' "$legacy_listed" | grep -Fxq "$LEGACY_NAME"; then
    echo "[legacy] retirando agente legado $LEGACY_NAME"
    if [[ -d "$LEGACY_HOME" ]]; then
        cd "$LEGACY_HOME"
        sudo -u ubuntu ./config.sh remove --token "$REG_TOKEN"
        ./svc.sh uninstall "$LEGACY_SERVICE"
    else
        echo "WARN: $LEGACY_HOME ausente, saltando config.sh remove del legado" >&2
    fi
else
    echo "[legacy] no hay agente legado $LEGACY_NAME en GitHub — nada que migrar"
fi

# === 7) FASE 1 — baja de agentes NUMERADOS sobrantes.
#       `agents.list` es la fuente de verdad para cuántos agentes numerados existen en esta VM.
#       Si `RUNNER_COUNT` < `length(agents.list)`, los que sobren hay que retirarlos — pero solo
#       si están inactivos; si están `active` con un job en vuelo, abortar con `set -e` para que
#       el operador espere (R3.2 / D3).
expected_names=()
for i in $(seq 1 "$RUNNER_COUNT"); do
    expected_names+=("autohostai-${ENV}-vm-${i}")
done

declared_names=()
if [[ -s "$AGENTS_LIST" ]]; then
    while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        declared_names+=("$line")
    done < "$AGENTS_LIST"
fi

# declared \ expected = surplus
surplus=()
for name in "${declared_names[@]+"${declared_names[@]}"}"; do
    skip=0
    for exp in "${expected_names[@]}"; do
        if [[ "$exp" == "$name" ]]; then skip=1; break; fi
    done
    [[ "$skip" -eq 1 ]] && continue
    surplus+=("$name")
done

for name in "${surplus[@]+"${surplus[@]}"}"; do
    # Defensa en profundidad: si `agents.list` fue editado a mano con un nombre que no encaja,
    # no producir un `...-vm-.service` inválido (y abortar `set -e` por regex fail en `retire_named_agent`).
    if [[ ! "$name" =~ ^autohostai-${ENV}-vm-([0-9]+)$ ]]; then
        echo "WARN: $name no encaja con el patrón, saltando" >&2
        continue
    fi
    svc="${SERVICE_PREFIX}-${name##*-}.service"   # autohostai-...-vm-<i> → actions.runner...-<i>.service
    state="$(systemctl is-active "$svc" 2>&1 || true)"
    case "$state" in
        failed|inactive|unknown)
            echo "[surplus] retirando $name (svc=$state)"
            retire_named_agent "$name"
            ;;
        active)
            url="$(gh_in_progress_url_for_runner "$name" || true)"
            if [[ -n "$url" ]]; then
                echo "ERROR: agente $name activo con job en vuelo: $url" >&2
                echo "ERROR: cancelar el PR (o esperar a que termine) antes de reaplicar el bootstrap" >&2
            else
                echo "ERROR: agente $name activo pero sin job en vuelo en la API" >&2
                echo "ERROR: cancelar el job en GitHub y reaplicar" >&2
            fi
            exit 1
            ;;
        *)
            echo "ERROR: estado desconocido '$state' del servicio $svc" >&2
            exit 1
            ;;
    esac
done

# === 8) FASE 2 — bucle de registro. Tolerante a fallos por agente (R3.3 — "dejar a los agentes
#       1..k-1 reconciliados si el agente k falla"). Cada iteración corre en una subshell con su
#       propio `set -e`; aquí solo se cuenta con `had_failure` y se imprime el resumen.
agents_temp="$(mktemp "${AGENTS_LIST}.XXXXXX")"
trap 'rm -f "$agents_temp"' EXIT
had_failure=0

for i in $(seq 1 "$RUNNER_COUNT"); do
    if install_named_agent "$i"; then
        # Solo escribimos el nombre al temp si el agente quedó completamente registrado Y
        # su servicio quedó activo/idempotente. Una iteración que falla NO toca este temp.
        echo "autohostai-${ENV}-vm-${i}" >> "$agents_temp"
    else
        rc=$?
        echo "ERROR: agent $i/$RUNNER_COUNT failed (rc=$rc); agentes previos reconciliados, restantes sin tocar" >&2
        had_failure=1
    fi
done

# Escritura atómica del agents.list desde el temp (D3 / R3 service-discovery).
mv -f "$agents_temp" "$AGENTS_LIST"
trap - EXIT   # el temp ya no existe (lo mvimos); limpiar el trap evita `rm -f` espurio al salir.

unset REG_TOKEN INSTALL_TOKEN

if [[ "$had_failure" -ne 0 ]]; then
    exit 1
fi

echo "[bootstrap] pool registrado: $(tr '\n' ' ' < "$AGENTS_LIST")(label: ${ENV})."