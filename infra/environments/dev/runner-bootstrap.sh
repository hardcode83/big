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
# se pasa a `config.sh --token`/`config.sh remove --token` por argv — inevitable, y NO es de un
# solo uso: el mismo token sirve para los N registros/retiradas de esta ejecución (D5), vive ~1h
# y `/proc/<pid>/cmdline` de cada `config.sh` en curso es legible por cualquier usuario de la VM
# mientras ese proceso vive. Mitigación real: Fase 2 registra los N agentes (config.sh) ANTES de
# arrancar ningún servicio, así que ningún agente puede estar aceptando jobs mientras el token de
# otro registro sigue en argv (corrección del panel de `/sdd:review`, `sdd-security`, 2026-09-04
# — la versión anterior arrancaba el servicio de cada agente antes de que terminasen los demás).
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
# Hook de inicio de job (change ci-runner-workspace-pollution, R3.2). Ruta canónica FIJA, misma
# convención que `/opt/gh-app-install-token.py`: la escribe el `write_files` del cloud-init en una
# VM nueva, y el `sudo install -m0755` del RUNBOOK §6.2 en la VM viva. Este script la asume
# presente y la copia al `hooks/` de cada agente.
HOOK_SRC=/opt/runner-job-started.sh
HOOK_NAME=runner-job-started.sh

mkdir -p "$AGENTS_DIR"
# Grupo docker: cloud-init lo crea; reasegurar para el alta out-of-band.
getent group docker >/dev/null || groupadd docker

# Grupo + sudoers para que los agentes numerados puedan hacer lo que el legado `ubuntu` ya
# podía (`ubuntu ALL=(ALL) NOPASSWD:ALL`, grant de cloud-init). Sin esto, cualquier paso de
# job que necesite `sudo` (p. ej. `playwright install --with-deps` de frontend-tests.yml,
# que instala dependencias del SO) falla con "a password is required" — hallazgo en la VM
# real, 2026-09-04, primer job real corrido en el pool nuevo tras la migración.
# Gotcha de migración (una sola vez): un agente que YA estaba `active` cuando esta versión
# se aplicó por primera vez no recoge la nueva membresía del grupo hasta que se reinicia su
# servicio (`usermod -aG` no afecta a un proceso ya en marcha) — `start_named_agent` deja un
# servicio `active` intacto, así que el reinicio, la primera vez, es manual
# (`systemctl restart <servicio>` por agente). Los agentes creados por esta versión en
# adelante ya nacen con el grupo, sin este paso.
getent group ci-agents >/dev/null || groupadd ci-agents
if [[ ! -f /etc/sudoers.d/91-actions-runner-pool ]]; then
    echo '%ci-agents ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/91-actions-runner-pool
    chmod 0440 /etc/sudoers.d/91-actions-runner-pool
    visudo -c -f /etc/sudoers.d/91-actions-runner-pool || {
        rm -f /etc/sudoers.d/91-actions-runner-pool
        echo "ERROR: sudoers drop-in inválido, no se ha aplicado" >&2
        exit 1
    }
fi

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
#       Retira también el PRINCIPAL LOCAL (usuario Linux + membresía del grupo docker + home):
#       sin esto, `actions-runner-<i>` sobrevive a la baja como cuenta root-equivalente sobre
#       el socket de Docker y con alcance a instance principal (169.254.169.254) sin que ningún
#       job de GitHub lo justifique — el número de principales solo crecería, nunca bajaría
#       (hallazgo del panel de `/sdd:review`, `sdd-security`, 2026-09-04).
retire_named_agent() {
    local name="$1"
    if ! [[ "$name" =~ ^autohostai-${ENV}-vm-([0-9]+)$ ]]; then
        echo "ERROR: nombre de agente numerado $name no encaja con el patrón esperado" >&2
        return 1
    fi
    local i="${BASH_REMATCH[1]}"
    local runner_user="actions-runner-${i}"
    local home="/opt/actions-runner-${i}"
    local svc="${SERVICE_PREFIX}-${i}.service"
    if [[ -d "$home" ]]; then
        cd "$home"
        # ORDEN OBLIGATORIO: `svc.sh uninstall` primero. `config.sh remove` se niega con
        # "Uninstall service first" mientras el servicio systemd siga instalado, esté
        # `active` o `inactive` — parar el servicio (systemctl stop) no basta, hay que
        # desinstalarlo (hallazgo en la VM real, 2026-09-04, durante la verificación
        # post-merge D7/5.3).
        ./svc.sh uninstall "$svc"
        sudo -u "$runner_user" ./config.sh remove --token "$REG_TOKEN"
    else
        echo "WARN: home $home ausente, saltando config.sh remove para $name" >&2
    fi
    cd /
    if id "$runner_user" >/dev/null 2>&1; then
        gpasswd -d "$runner_user" docker >/dev/null 2>&1 || true
        userdel -r "$runner_user" 2>/dev/null || userdel "$runner_user" 2>/dev/null || \
            echo "WARN: no se pudo borrar el usuario $runner_user (¿procesos vivos del propio usuario?)" >&2
    fi
    rm -rf "$home"
}

# === 5) Helpers: registrar y arrancar un agente NUMERADO, en dos fases separadas.
#       Separados a propósito (D3, corrección de seguridad 2026-09-04): registrar TODOS los
#       agentes antes de arrancar CUALQUIER servicio, para que ningún agente esté ya aceptando
#       jobs mientras el REG_TOKEN sigue en el argv de un `config.sh` hermano en curso.
#       Cada uno corre en su propia subshell con `set -e` aislado. Devuelven 0 si OK; cualquier
#       fallo imprime "agent <i>/<N>: <step>: failed" y devuelve !=0. El step concreto lo
#       captura un trap ERR contra la variable `step` (vía función para que se evalúe al FALLAR,
#       no al instalar el trap — un `'...$step...'` en single-quotes capturaría el valor vacío
#       de `step` y diría "agent k/N: failed" sin contexto).
register_named_agent() {
    local i="$1"
    local runner_user="actions-runner-${i}"
    local runner_home="/opt/actions-runner-${i}"
    local agent_name="autohostai-${ENV}-vm-${i}"
    local step=""
    (
        set -euo pipefail
        on_err() {
            echo "agent ${i}/${RUNNER_COUNT}: ${step} failed" >&2
            exit 1
        }
        trap on_err ERR

        step="ensure user $runner_user"
        if ! id "$runner_user" >/dev/null 2>&1; then
            useradd -m -s /bin/bash "$runner_user"
        fi
        usermod -aG docker,ci-agents "$runner_user"

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
    )
}

# === 5.b) Helpers del hook de inicio de job (change ci-runner-workspace-pollution, R3.2) ===
#       Se llaman desde el CUERPO del script (Fase 2), NO desde la subshell de
#       `register_named_agent`: `write_runner_env` produce un booleano ("¿cambió el .env?") que
#       `start_named_agent` necesita para decidir el reinicio (D4), y una subshell `( ... )` no
#       puede devolver una variable a su padre. La instalación del fichero sí sería inocua dentro
#       de la subshell (copiar un fichero idéntico es un no-op), pero se mantiene junto a la
#       escritura del `.env` para que el par viva en un solo sitio.

# Copia el hook a `$RUNNER_HOME/hooks/runner-job-started.sh` del agente `i`, con dueño el propio
# usuario del agente (el proceso del runner corre como él y tiene que poder leerlo y ejecutarlo)
# y modo 0755 (el mismo que le da el cloud-init en `/opt`). `install` fija el modo explícitamente,
# así que el `umask 077` de arriba no lo recorta. Idempotente por contenido: re-copiar un fichero
# byte a byte idéntico no cambia nada observable.
install_job_started_hook() {
    local i="$1"
    local runner_user="actions-runner-${i}"
    local runner_home="/opt/actions-runner-${i}"
    if [[ ! -f "$HOOK_SRC" ]]; then
        echo "ERROR: agent $i/$RUNNER_COUNT: falta $HOOK_SRC — lo escribe el cloud-init en una VM nueva; en la VM viva, 'sudo install -m0755 runner-job-started.sh $HOOK_SRC' (RUNBOOK §6.2)" >&2
        return 1
    fi
    install -d -o "$runner_user" -g "$runner_user" -m 0755 "$runner_home/hooks"
    install -o "$runner_user" -g "$runner_user" -m 0755 "$HOOK_SRC" "$runner_home/hooks/$HOOK_NAME"
}

# Declara `ACTIONS_RUNNER_HOOK_JOB_STARTED=<hook_path>` en el `.env` del agente, PRESERVANDO
# cualquier otra clave que el fichero ya tuviera (nadie más escribe ahí hoy, pero el fichero es
# del runner, no nuestro). Si la clave ya estaba, se sustituye en su sitio; si no, se añade al
# final; si estaba duplicada, se colapsa en una sola línea.
#
# Imprime EXACTAMENTE una palabra en stdout: `changed` si el contenido resultante difiere del que
# había en disco (→ el proceso del runner sigue con el entorno viejo y hay que reiniciarlo, D3),
# o `unchanged` si ya estaba correcto (→ no tocar un servicio vivo, D4). Los diagnósticos van a
# stderr para no contaminar esa palabra. Devuelve !=0 si la escritura falla.
#
# El `.env` NO lo carga ni `runsvc.sh` ni la unit de systemd: lo lee el propio proceso del runner
# al arrancar, y por eso la doc de GitHub dice, literal, "any change to the .env file will require
# restarting the runner" (D3). Escribirlo sobre un runner vivo no activa el hook por sí solo.
#
# Escritura atómica (temp + mv) y modo 0600, misma idea que el `agents.list` de más abajo: el
# fichero no tiene por qué ser legible por el resto de la VM.
#
# Uso: write_runner_env <env_file> <hook_path> <runner_user>
write_runner_env() {
    local env_file="$1"
    local hook_path="$2"
    local runner_user="$3"
    local key="ACTIONS_RUNNER_HOOK_JOB_STARTED"
    local desired="${key}=${hook_path}"

    local before=""
    if [[ -f "$env_file" ]]; then
        before="$(cat "$env_file")" || return 1
    fi

    local -a lines=()
    local replaced=0 line
    if [[ -f "$env_file" ]]; then
        # `|| [[ -n "$line" ]]`: un fichero cuya última línea no acaba en \n no se pierde.
        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" == "${key}="* ]]; then
                if [[ "$replaced" -eq 0 ]]; then
                    lines+=("$desired")
                    replaced=1
                fi
                continue   # duplicados de la misma clave: se colapsan en la primera
            fi
            lines+=("$line")
        done < "$env_file"
    fi
    if [[ "$replaced" -eq 0 ]]; then
        lines+=("$desired")
    fi

    # `$(...)` recorta los \n finales por igual en los dos lados, así que la comparación no
    # depende de si el fichero original terminaba o no en salto de línea.
    local after
    after="$(printf '%s\n' "${lines[@]}")"
    if [[ -f "$env_file" && "$after" == "$before" ]]; then
        printf 'unchanged\n'
        return 0
    fi

    local tmp
    tmp="$(mktemp "${env_file}.XXXXXX")" || return 1
    printf '%s\n' "${lines[@]}" > "$tmp" || { rm -f "$tmp"; return 1; }
    chown "${runner_user}:${runner_user}" "$tmp" || { rm -f "$tmp"; return 1; }
    chmod 0600 "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$env_file" || { rm -f "$tmp"; return 1; }
    printf 'changed\n'
}

# Arranca el servicio de un agente ya registrado. Se llama SOLO después de que todos los
# `register_named_agent` de esta pasada hayan terminado (Fase 2, más abajo).
#   $1 — índice `i` del agente.
#   $2 — `1` si el `.env` de este agente CAMBIÓ en esta pasada (ver `write_runner_env`), `0` si no.
#        Solo se LEE aquí dentro, así que cruzar la frontera de la subshell como argumento posicional
#        basta: nada tiene que volver al padre.
#   Códigos de salida: 0 = OK; 2 = el `.env` cambió pero el agente tiene un job en vuelo, así que el
#   reinicio queda DIFERIDO (no es un fallo — el llamador lo anota en el resumen final, no en
#   `had_failure`); cualquier otro !=0 = fallo real.
start_named_agent() {
    local i="$1"
    local env_changed="${2:-0}"
    local runner_user="actions-runner-${i}"
    local runner_home="/opt/actions-runner-${i}"
    local agent_name="autohostai-${ENV}-vm-${i}"
    local svc="${SERVICE_PREFIX}-${i}.service"
    local step=""
    (
        set -euo pipefail
        on_err() {
            echo "agent ${i}/${RUNNER_COUNT}: ${step} failed" >&2
            exit 1
        }
        trap on_err ERR

        step="svc.sh install/start $svc"
        cd "$runner_home"
        state="$(systemctl is-active "$svc" 2>&1 || true)"
        case "$state" in
            active)
                # Ya activo. Hasta el change ci-runner-workspace-pollution esto era "no tocar", y
                # sigue siéndolo salvo por UN caso: si el `.env` de este agente cambió en esta
                # pasada, el proceso vivo arrancó con el entorno ANTERIOR y no tiene
                # ACTIONS_RUNNER_HOOK_JOB_STARTED — ese fichero no lo carga systemd ni `runsvc.sh`,
                # lo lee el propio proceso del runner al arrancar (D3; doc de GitHub, literal:
                # "any change to the .env file will require restarting the runner"). Dejarlo así
                # instalaría el hook sin que NINGÚN runner lo releyese: el fallo silencioso más
                # probable de este change (D4).
                # El reinicio se condiciona a que el agente no tenga un job en vuelo — misma
                # guardia de liveness que la Fase 1 (`systemctl is-active` + la API de GitHub).
                if [[ "$env_changed" -eq 1 ]]; then
                    step="restart $svc (.env cambiado)"
                    # api_rc por separado de `url`, y NUNCA `|| true`: un fallo de la API (token
                    # expirado, 403/429, timeout) no es lo mismo que "sin job en vuelo" — antes de
                    # esta corrección los dos colapsaban al mismo `url` vacío, y un `systemctl
                    # restart` sobre un agente con un job real en marcha lo mataría en silencio
                    # (hallazgo del panel de `/sdd:review`, `sdd-security`, 2026-09-15). El resto
                    # de llamadas a `gh_in_progress_url_for_runner` en este script no necesitan
                    # esta distinción: sus dos ramas (fallo de API vs. job en vuelo confirmado)
                    # ya bloquean por igual sin ejecutar nada destructivo.
                    api_rc=0
                    url="$(gh_in_progress_url_for_runner "$agent_name")" || api_rc=$?
                    if [[ "$api_rc" -ne 0 ]]; then
                        echo "[hook] agent $i/$RUNNER_COUNT: $svc activo, .env cambiado — la API de GitHub no respondió; no se reinicia por precaución."
                        echo "[hook]   El .env ya declara ACTIONS_RUNNER_HOOK_JOB_STARTED en disco, pero el proceso vivo aún no lo ha leído."
                        echo "[hook]   Comprobar a mano si tiene un job en vuelo y ejecutar 'systemctl restart $svc' cuando esté ocioso (o reaplicar este bootstrap entonces)."
                        exit 2
                    fi
                    if [[ -n "$url" ]]; then
                        echo "[hook] agent $i/$RUNNER_COUNT: $svc activo CON job en vuelo ($url) — no se reinicia."
                        echo "[hook]   El .env ya declara ACTIONS_RUNNER_HOOK_JOB_STARTED en disco, pero el proceso vivo aún no lo ha leído."
                        echo "[hook]   Ejecutar 'systemctl restart $svc' cuando el agente quede ocioso (o reaplicar este bootstrap entonces)."
                        exit 2
                    fi
                    systemctl restart "$svc"
                    echo "[hook] agent $i/$RUNNER_COUNT: $svc reiniciado — el runner ya lee ACTIONS_RUNNER_HOOK_JOB_STARTED."
                fi
                ;;
            failed|inactive|unknown)
                # Arranque desde cero: el proceso nace DESPUÉS de escribir el `.env`, así que lo lee
                # sin más — no hay nada que reiniciar aquí.
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
#       retirado porque el bucle solo registra nombres numerados). Misma guardia de liveness
#       que la Fase 1 (systemctl is-active): un legado con un job en vuelo no se retira a medias
#       (hallazgo del panel de `/sdd:review`, `sdd-security`, 2026-09-04). El usuario `ubuntu`
#       en sí NO se toca — es la cuenta base de la VM, no un principal de agente; solo se limpia
#       el directorio `$LEGACY_HOME` del runner legado.
echo "[bootstrap] RUNNER_COUNT=$RUNNER_COUNT, ENV=$ENV"
legacy_listed="$(gh_list_runner_names)"
if printf '%s\n' "$legacy_listed" | grep -Fxq "$LEGACY_NAME"; then
    legacy_state="$(systemctl is-active "$LEGACY_SERVICE" 2>&1 || true)"
    case "$legacy_state" in
        failed|inactive|unknown)
            echo "[legacy] retirando agente legado $LEGACY_NAME (svc=$legacy_state)"
            if [[ -d "$LEGACY_HOME" ]]; then
                cd "$LEGACY_HOME"
                # ORDEN OBLIGATORIO: `svc.sh uninstall` primero — ver nota de
                # `retire_named_agent` más arriba (mismo hallazgo, misma causa).
                ./svc.sh uninstall "$LEGACY_SERVICE"
                sudo -u ubuntu ./config.sh remove --token "$REG_TOKEN"
                cd /
                rm -rf "$LEGACY_HOME"
            else
                echo "WARN: $LEGACY_HOME ausente, saltando config.sh remove del legado" >&2
            fi
            ;;
        active)
            url="$(gh_in_progress_url_for_runner "$LEGACY_NAME" || true)"
            if [[ -n "$url" ]]; then
                echo "ERROR: agente legado $LEGACY_NAME activo con job en vuelo: $url" >&2
            else
                echo "ERROR: agente legado $LEGACY_NAME activo pero sin job en vuelo en la API" >&2
            fi
            echo "ERROR: esperar a que termine (o cancelar el PR) antes de reaplicar el bootstrap" >&2
            exit 1
            ;;
        *)
            echo "ERROR: estado desconocido '$legacy_state' del servicio $LEGACY_SERVICE" >&2
            exit 1
            ;;
    esac
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

# Recolecta TODOS los agentes bloqueados antes de abortar — un solo mensaje con la lista
# completa, no un abort-y-reintenta por cada uno (hallazgo del panel de `/sdd:review`,
# `sdd-qa`, 2026-09-04: con varios agentes `active` a la vez, abortar en el primero obliga
# al operador a reaplicar N veces para descubrir los demás uno por uno).
blocked=()
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
                blocked+=("$name activo con job en vuelo: $url")
            else
                blocked+=("$name activo pero sin job en vuelo en la API — cancelar el job en GitHub y reaplicar")
            fi
            ;;
        *)
            blocked+=("$name en estado desconocido '$state' del servicio $svc")
            ;;
    esac
done

if [[ "${#blocked[@]}" -gt 0 ]]; then
    echo "ERROR: ${#blocked[@]} agente(s) sobrante(s) no se pueden retirar todavía:" >&2
    for b in "${blocked[@]}"; do
        echo "ERROR:   - $b" >&2
    done
    echo "ERROR: esperar a que terminen (o cancelar el/los PR) antes de reaplicar el bootstrap" >&2
    exit 1
fi

# === 8) FASE 2 — dos pasadas: registrar TODOS los agentes primero, arrancar servicios después
#       (ver comentario de §5 — evita que un agente ya activo comparta VM con un REG_TOKEN aún
#       en argv de un `config.sh` hermano). Tolerante a fallos por agente (R3.3): el bucle de
#       registro NO se detiene en el primer fallo — intenta los N agentes siempre, igual que la
#       Fase 1 recolecta todos los bloqueados antes de abortar (misma filosofía: un informe
#       completo en una pasada, no un abort-y-reintenta por cada fallo). Un agente k que falla
#       no afecta a k+1..N: cada uno corre en su propia subshell aislada con su propio `set -e`.
#       Un agente cuyo `config.sh` tuvo éxito se cuenta como "declarado" (entra en `agents.list`)
#       AUNQUE el arranque del servicio falle después — de lo contrario quedaría registrado en
#       GitHub y huérfano en `agents.list`, invisible para la Fase 1 del siguiente
#       reaprovisionamiento (hallazgo del panel de `/sdd:review`, `sdd-qa`, 2026-09-04).
agents_temp="$(mktemp "${AGENTS_LIST}.XXXXXX")"
trap 'rm -f "$agents_temp"' EXIT
had_failure=0
registered_idx=()   # índices `i` cuyo config.sh tuvo éxito — pendientes de arrancar servicio
env_changed_idx=()  # índices `i` cuyo `.env` cambió en esta pasada → su runner debe releerlo (D3/D4)
deferred_restart=() # agentes con el `.env` ya correcto en disco pero con job en vuelo (D4)

for i in $(seq 1 "$RUNNER_COUNT"); do
    if register_named_agent "$i"; then
        registered_idx+=("$i")
        echo "autohostai-${ENV}-vm-${i}" >> "$agents_temp"
        # Hook de inicio de job (R3.2): aquí, en el cuerpo del script, NO dentro de la subshell de
        # `register_named_agent` — `write_runner_env` produce el booleano que decide el reinicio y
        # una subshell no puede devolvérselo al padre (ver §5.b). Mismo gate que `registered_idx`:
        # solo tiene sentido sobre un agente cuyo `config.sh` fue bien.
        runner_home="/opt/actions-runner-${i}"
        hook_state=""
        if install_job_started_hook "$i" \
            && hook_state="$(write_runner_env "$runner_home/.env" "$runner_home/hooks/$HOOK_NAME" "actions-runner-${i}")"; then
            if [[ "$hook_state" == "changed" ]]; then
                env_changed_idx+=("$i")
                echo "[hook] agent $i/$RUNNER_COUNT: .env actualizado (ACTIONS_RUNNER_HOOK_JOB_STARTED) — requiere reinicio del runner"
            fi
        else
            rc=$?
            # No aborta el bucle (R3.3, misma filosofía que el resto de la fase): el agente queda
            # registrado y arrancará, solo que sin el hook — y `had_failure` lo hace visible.
            echo "ERROR: agent $i/$RUNNER_COUNT: instalación/declaración del hook de inicio de job falló (rc=$rc); el agente seguirá sin el hook" >&2
            had_failure=1
        fi
    else
        rc=$?
        echo "ERROR: agent $i/$RUNNER_COUNT config.sh failed (rc=$rc); se sigue intentando con los agentes restantes" >&2
        had_failure=1
    fi
done

for i in "${registered_idx[@]+"${registered_idx[@]}"}"; do
    env_changed=0
    for c in "${env_changed_idx[@]+"${env_changed_idx[@]}"}"; do
        if [[ "$c" == "$i" ]]; then env_changed=1; break; fi
    done
    start_rc=0
    start_named_agent "$i" "$env_changed" || start_rc=$?
    if [[ "$start_rc" -eq 2 ]]; then
        # Reinicio diferido por job en vuelo: no es un fallo (el `.env` está bien en disco), pero
        # tiene que verse en el resumen final o el operador se va creyendo que el hook ya actúa.
        deferred_restart+=("autohostai-${ENV}-vm-${i} → systemctl restart ${SERVICE_PREFIX}-${i}.service")
    elif [[ "$start_rc" -ne 0 ]]; then
        echo "ERROR: agent $i/$RUNNER_COUNT svc.sh failed (rc=$start_rc); registrado en GitHub pero el servicio no arrancó — sigue en agents.list para el siguiente reaprovisionamiento" >&2
        had_failure=1
    fi
done

# Escritura atómica del agents.list desde el temp (D3 / R3 service-discovery).
mv -f "$agents_temp" "$AGENTS_LIST"
trap - EXIT   # el temp ya no existe (lo mvimos); limpiar el trap evita `rm -f` espurio al salir.

unset REG_TOKEN INSTALL_TOKEN

if [[ "${#deferred_restart[@]}" -gt 0 ]]; then
    echo "[hook] ${#deferred_restart[@]} agente(s) con ACTIONS_RUNNER_HOOK_JOB_STARTED escrito en disco pero PENDIENTES de reinicio (job en vuelo):"
    for d in "${deferred_restart[@]}"; do
        echo "[hook]   - $d"
    done
    echo "[hook] hasta que se reinicien, esos agentes NO ejecutan el hook de inicio de job."
fi

if [[ "$had_failure" -ne 0 ]]; then
    exit 1
fi

echo "[bootstrap] pool registrado: $(tr '\n' ' ' < "$AGENTS_LIST")(label: ${ENV})."