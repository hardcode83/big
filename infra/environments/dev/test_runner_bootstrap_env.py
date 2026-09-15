"""Suite of `runner-bootstrap.sh`'s `write_runner_env` helper (`ci-runner-workspace-pollution` R3.2).

`write_runner_env` is the one piece of section 4 that is pure enough to test from a laptop: it
merges `ACTIONS_RUNNER_HOOK_JOB_STARTED=<hook path>` into an agent's `$RUNNER_HOME/.env`,
preserving every other key, and reports `changed`/`unchanged` on stdout. That word is what
decides whether `start_named_agent` restarts a LIVE runner (design D3/D4) — a wrong `unchanged`
means the hook is installed and no runner ever reads it (the silent failure this change exists to
avoid), and a wrong `changed` bounces healthy agents on every re-provision. It is worth a
regression test.

**How it is driven, and why not by sourcing the script.** `runner-bootstrap.sh` cannot be
`source`d here: its very first statements `source /etc/autohostai-deploy.env` and mint a GitHub
App installation token from the OCI Vault via instance-principal auth. So this module extracts
just the `write_runner_env` function text out of the real script (see `extract_function`) and runs
it in an isolated `bash -euo pipefail` subshell against real temporary directories — same spirit
as `test_runner_job_started.py` driving the hook through `subprocess`, never mocking the code
under test. The extraction is anchored on the script's own convention (functions open with
`<name>() {` at column 0 and close with `}` at column 0), and `test_extraction_is_anchored_on_the_real_script`
fails loudly if that convention ever changes, rather than silently testing a stale copy.

**One stub, and why.** `write_runner_env` ends with `chown "$user:$user"` so the agent's own
runner process can read its `.env`. An unprivileged test process cannot chown a file to a
different owner, and "chown it to myself" is not portable either (on macOS the login group is not
named after the user). So `chown` is stubbed via a `PATH`-prepended directory — the same technique
`test_runner_job_started.py` uses for `find`/`sudo`, and never by patching the function itself.
Everything else the function does is real: `mktemp`, the temp+`mv` atomic write, `chmod 0600`,
and the whole merge/compare. `test_chown_failure_leaves_the_previous_env_intact` flips that stub
to failing to prove the atomic write does not corrupt an existing `.env`.

What this file does NOT cover, because it genuinely needs the VM: `install_job_started_hook`
(needs root and real `actions-runner-<i>` users), and whether the runner process actually picks
the variable up after a real restart. Those are section 6's manual verification on the live VM.

`start_named_agent`'s restart-decision branches (env_changed × active/idle/busy/not-yet-running,
D4's "don't restart an agent with a job in flight") ARE covered below, extracted and driven the
same way as `write_runner_env` above — `systemctl` stubbed via `PATH`, `gh_in_progress_url_for_runner`
stubbed as an overridable shell function, and `cd` itself shadowed as a shell function for the
duration of the call (the only way to redirect the function's *hardcoded* `/opt/actions-runner-<i>`
path onto a writable temp dir without root). See `start_named_agent`'s docstring below for the
detail on each stub.
"""

import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).with_name("runner-bootstrap.sh")
KEY = "ACTIONS_RUNNER_HOOK_JOB_STARTED"
HOOK_PATH = "/opt/actions-runner-2/hooks/runner-job-started.sh"
RUNNER_USER = "actions-runner-2"


def extract_function(name: str) -> str:
    """The text of one top-level function of `runner-bootstrap.sh`, verbatim.

    Anchored on the script's own layout: `<name>() {` at column 0, closed by `}` at column 0.
    """
    source = BOOTSTRAP.read_text()
    match = re.search(rf"^{re.escape(name)}\(\) \{{$", source, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{name}() not found at column 0 in {BOOTSTRAP}")
    end = re.search(r"^\}$", source[match.start():], re.MULTILINE)
    if end is None:
        raise AssertionError(f"{name}() has no closing brace at column 0 in {BOOTSTRAP}")
    return source[match.start():match.start() + end.end()]


def make_chown_stub(tmp_path: Path, *, exit_code: int) -> Path:
    """A directory holding a stub `chown`, to prepend onto PATH (see the module docstring)."""
    stub_dir = tmp_path / f"stub-bin-{exit_code}"
    stub_dir.mkdir(exist_ok=True)  # several calls per test reuse the same stub
    chown = stub_dir / "chown"
    chown.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        exit {exit_code}
    """))
    chown.chmod(0o755)
    return stub_dir


def write_runner_env(
    env_file: Path,
    tmp_path: Path,
    *,
    hook_path: str = HOOK_PATH,
    runner_user: str = RUNNER_USER,
    chown_exit: int = 0,
):
    """Run the real `write_runner_env` from the script against `env_file`."""
    program = "\n".join([
        "set -euo pipefail",
        "umask 077",  # as runner-bootstrap.sh sets it, so the mode assertions mean something
        extract_function("write_runner_env"),
        'write_runner_env "$1" "$2" "$3"',
    ])
    env = dict(os.environ)
    env["PATH"] = f"{make_chown_stub(tmp_path, exit_code=chown_exit)}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", "-c", program, "_", str(env_file), hook_path, runner_user],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def verdict(result) -> str:
    """The one word `write_runner_env` prints on stdout."""
    assert result.returncode == 0, f"rc={result.returncode} stderr={result.stderr}"
    return result.stdout.strip()


# --- Extraction is honest ---------------------------------------------------------------------


def test_extraction_is_anchored_on_the_real_script():
    """Fail loudly if the script's layout drifts, instead of testing a stale/empty copy."""
    body = extract_function("write_runner_env")
    assert body.startswith("write_runner_env() {")
    assert body.endswith("\n}")
    assert KEY in body, "the extracted function no longer mentions the variable it declares"
    assert "printf 'changed\\n'" in body and "printf 'unchanged\\n'" in body


# --- The merge itself -------------------------------------------------------------------------


def test_absent_env_is_created_with_the_declaration(tmp_path):
    env_file = tmp_path / ".env"
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == f"{KEY}={HOOK_PATH}\n"


def test_created_env_is_0600(tmp_path):
    env_file = tmp_path / ".env"
    write_runner_env(env_file, tmp_path)
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_rerun_is_a_genuine_no_op(tmp_path):
    """Idempotency: the second pass must say `unchanged` and not touch the file at all.

    This is the assertion that protects live agents — an `unchanged` that lied the other way
    would restart every runner on every re-provision, and a `changed` that lied would be caught
    by the tests above.
    """
    env_file = tmp_path / ".env"
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    before = (env_file.read_text(), env_file.stat().st_mtime_ns, env_file.stat().st_ino)
    assert verdict(write_runner_env(env_file, tmp_path)) == "unchanged"
    after = (env_file.read_text(), env_file.stat().st_mtime_ns, env_file.stat().st_ino)
    assert before == after


def test_other_keys_are_preserved_and_the_declaration_appended(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LANG=C.UTF-8\nhttps_proxy=http://proxy:3128\n")
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == (
        f"LANG=C.UTF-8\nhttps_proxy=http://proxy:3128\n{KEY}={HOOK_PATH}\n"
    )
    assert verdict(write_runner_env(env_file, tmp_path)) == "unchanged"


def test_existing_declaration_with_another_value_is_replaced_in_place(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"LANG=C.UTF-8\n{KEY}=/opt/actions-runner-2/hooks/OLD.sh\nTZ=UTC\n")
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    # Replaced where it was — surrounding keys keep their relative order.
    assert env_file.read_text() == f"LANG=C.UTF-8\n{KEY}={HOOK_PATH}\nTZ=UTC\n"


def test_correct_declaration_among_other_keys_is_left_alone(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"LANG=C.UTF-8\n{KEY}={HOOK_PATH}\nTZ=UTC\n")
    before = env_file.stat().st_mtime_ns
    assert verdict(write_runner_env(env_file, tmp_path)) == "unchanged"
    assert env_file.stat().st_mtime_ns == before


def test_duplicate_declarations_collapse_to_one(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{KEY}=/old/a.sh\nTZ=UTC\n{KEY}=/old/b.sh\n")
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == f"{KEY}={HOOK_PATH}\nTZ=UTC\n"
    assert verdict(write_runner_env(env_file, tmp_path)) == "unchanged"


def test_last_line_without_a_trailing_newline_is_not_lost(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LANG=C.UTF-8\nTZ=UTC")  # no trailing newline
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == f"LANG=C.UTF-8\nTZ=UTC\n{KEY}={HOOK_PATH}\n"


def test_blank_lines_and_comments_survive(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# puesto a mano\n\nLANG=C.UTF-8\n")
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == f"# puesto a mano\n\nLANG=C.UTF-8\n{KEY}={HOOK_PATH}\n"
    assert verdict(write_runner_env(env_file, tmp_path)) == "unchanged"


def test_empty_env_file_gets_the_declaration(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == f"{KEY}={HOOK_PATH}\n"


def test_values_with_spaces_are_not_word_split(tmp_path):
    """A pre-existing key whose value has spaces must come back byte-identical."""
    env_file = tmp_path / ".env"
    env_file.write_text('GOFLAGS=-ldflags "-s -w"\n')
    assert verdict(write_runner_env(env_file, tmp_path)) == "changed"
    assert env_file.read_text() == f'GOFLAGS=-ldflags "-s -w"\n{KEY}={HOOK_PATH}\n'


def test_each_agent_gets_its_own_absolute_hook_path(tmp_path):
    """R3.2 per agent `i`: the declared path is the agent's OWN installed hook, not a shared one."""
    for i in (1, 4):
        home = tmp_path / f"actions-runner-{i}"
        home.mkdir()
        hook = f"/opt/actions-runner-{i}/hooks/runner-job-started.sh"
        result = write_runner_env(
            home / ".env", tmp_path, hook_path=hook, runner_user=f"actions-runner-{i}"
        )
        assert verdict(result) == "changed"
        assert (home / ".env").read_text() == f"{KEY}={hook}\n"


# --- Failure path -----------------------------------------------------------------------------


def test_chown_failure_leaves_the_previous_env_intact(tmp_path):
    """A failed `chown` must abort the write, not half-apply it, and not leave a temp behind."""
    env_file = tmp_path / ".env"
    original = "LANG=C.UTF-8\n"
    env_file.write_text(original)
    result = write_runner_env(env_file, tmp_path, chown_exit=1)
    assert result.returncode != 0
    assert env_file.read_text() == original
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".env.")]
    assert leftovers == [], f"temp file(s) left behind: {leftovers}"


def test_chown_failure_does_not_create_the_env_when_absent(tmp_path):
    env_file = tmp_path / ".env"
    result = write_runner_env(env_file, tmp_path, chown_exit=1)
    assert result.returncode != 0
    assert not env_file.exists()


# --- The wiring in the script around the helper -----------------------------------------------


def test_the_script_declares_the_hook_source_and_uses_it():
    """The canonical `/opt` source path and the per-agent install target, as section 4 wires them."""
    source = BOOTSTRAP.read_text()
    assert "HOOK_SRC=/opt/runner-job-started.sh" in source
    assert "HOOK_NAME=runner-job-started.sh" in source
    assert '"$runner_home/hooks/$HOOK_NAME"' in source


def test_bash_syntax_of_the_whole_script_is_valid():
    result = subprocess.run(["bash", "-n", str(BOOTSTRAP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    subprocess.run(["which", "shellcheck"], capture_output=True).returncode != 0,
    reason="shellcheck not installed on this host",
)
def test_shellcheck_is_clean():
    result = subprocess.run(
        ["shellcheck", "-S", "warning", str(BOOTSTRAP)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout


# =================================================================================================
# `start_named_agent`'s restart-decision branches (D4) — section 4 fix round, QA finding
# =================================================================================================
#
# Extends the extraction technique above to a second, harder function: `start_named_agent` decides
# whether to restart a LIVE runner whose `.env` just changed, and D4's whole point is that it must
# NOT restart one with a job in flight (`rc=2`, "deferred", not a failure). Before this fix round
# that branch had zero committed coverage — only an uncommitted scratch harness the implementer
# never checked in.

AGENT_ENV = "test"
AGENT_SERVICE_PREFIX = "actions.runner.test-org-test-repo.autohostai-test-vm"


def extract_snippet(start_line: str, end_line: str) -> str:
    """Verbatim script text from `start_line` (exact, column 0) to the next `end_line` (exact,
    column 0) found after it — inclusive of both lines. Same anchoring spirit as `extract_function`
    above, for a script region that is not itself a named function (the FASE 2 registration loop).
    """
    source = BOOTSTRAP.read_text()
    start = re.search(rf"^{re.escape(start_line)}$", source, re.MULTILINE)
    if start is None:
        raise AssertionError(f"start marker not found at column 0 in {BOOTSTRAP}: {start_line!r}")
    end = re.search(rf"^{re.escape(end_line)}$", source[start.start():], re.MULTILINE)
    if end is None:
        raise AssertionError(f"end marker not found at column 0 after start in {BOOTSTRAP}: {end_line!r}")
    return source[start.start():start.start() + end.end()]


def make_svc_stub(runner_home: Path, log: Path) -> None:
    """A stand-in `<runner_home>/svc.sh` — the real script's own install/start entrypoint for the
    "not active yet" branch. Records every invocation to `log` (an absolute path outside the
    redirected `cd`, so it is readable regardless of the function's cwd).
    """
    svc = runner_home / "svc.sh"
    svc.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "svc.sh $*" >> "{log}"
        exit 0
    """))
    svc.chmod(0o755)


def make_systemctl_stub(tmp_path: Path, *, state: str, restart_log: Path) -> Path:
    """A directory holding a stub `systemctl`, to prepend onto PATH (same technique as
    `make_chown_stub` above): `is-active` reports the fixed `state` this test wants, `restart`
    just logs that it was called and with which service name — real `systemctl` needs systemd,
    which this sandbox does not have.
    """
    stub_dir = tmp_path / f"stub-systemctl-{state}"
    stub_dir.mkdir(exist_ok=True)
    systemctl = stub_dir / "systemctl"
    systemctl.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [[ "$1" == "is-active" ]]; then
            printf '%s\\n' "{state}"
            [[ "{state}" == "active" ]] && exit 0 || exit 3
        elif [[ "$1" == "restart" ]]; then
            echo "restart $2" >> "{restart_log}"
            exit 0
        fi
        echo "unexpected systemctl invocation: $*" >&2
        exit 1
    """))
    systemctl.chmod(0o755)
    return stub_dir


def start_named_agent(
    i: int,
    env_changed: int,
    tmp_path: Path,
    *,
    service_state: str,
    in_progress_url: str = "",
    api_fails: bool = False,
):
    """Run the real `start_named_agent` from the script against a fake `/opt/actions-runner-<i>`.

    Three things the real function reaches outside the test process, and how each is faked —
    everything else (the `case`/`if` decision logic itself) is the genuine extracted code:

    - `runner_home` is *hardcoded inside the function* as `/opt/actions-runner-<i>`, not a
      parameter — an unprivileged test process cannot create or write there. So `cd` itself is
      shadowed by a shell function for the duration of this one call: it redirects only that exact
      path to a real temp directory (`builtin cd` for every other path, so nothing else breaks).
      This is the same "override, don't reimplement" spirit as the `chown` stub in
      `write_runner_env`'s tests above, applied to a builtin instead of an external command
      (confirmed inherited correctly into the function's own `( ... )` subshell).
    - `systemctl` is stubbed via `PATH` (see `make_systemctl_stub`).
    - `gh_in_progress_url_for_runner` — the function this reuses for its busy-check — is stubbed as
      an overridable shell *function*: `start_named_agent` is extracted alone (not together with
      the real helper), and our own same-named function, defined earlier in the program, is what
      the extracted body actually calls.

    `./svc.sh install`/`./svc.sh start` (the pre-existing "not active yet" branch) get a real stub
    script dropped into the fake runner home (see `make_svc_stub`), so that branch runs for real
    too — this fix round must not silently narrow coverage of the branch that already existed.
    """
    real_home = f"/opt/actions-runner-{i}"
    fake_home = tmp_path / f"actions-runner-{i}"
    fake_home.mkdir(parents=True, exist_ok=True)
    svc_log = tmp_path / "svc.log"
    restart_log = tmp_path / "systemctl-restart.log"
    gh_call_log = tmp_path / "gh-calls.log"
    make_svc_stub(fake_home, svc_log)
    stub_dir = make_systemctl_stub(tmp_path, state=service_state, restart_log=restart_log)

    program = "\n".join([
        "set -euo pipefail",
        f'ENV="{AGENT_ENV}"',
        f'SERVICE_PREFIX="{AGENT_SERVICE_PREFIX}"',
        'RUNNER_COUNT="3"',
        "cd() {",
        '    if [[ "$1" == "$REAL_HOME" ]]; then',
        '        builtin cd "$FAKE_HOME"',
        "    else",
        '        builtin cd "$@"',
        "    fi",
        "}",
        "gh_in_progress_url_for_runner() {",
        '    printf "%s\\n" "$1" >> "$GH_CALL_LOG"',
        '    if [[ "$GH_API_FAILS" == "1" ]]; then',
        "        return 1",
        "    fi",
        '    printf "%s" "$GH_URL"',
        "}",
        extract_function("start_named_agent"),
        'start_named_agent "$1" "$2"',
    ])
    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    env["REAL_HOME"] = real_home
    env["FAKE_HOME"] = str(fake_home)
    env["GH_CALL_LOG"] = str(gh_call_log)
    env["GH_URL"] = in_progress_url
    env["GH_API_FAILS"] = "1" if api_fails else "0"
    result = subprocess.run(
        ["bash", "-c", program, "_", str(i), str(env_changed)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    result.svc_log = svc_log.read_text() if svc_log.exists() else ""
    result.restart_log = restart_log.read_text() if restart_log.exists() else ""
    result.gh_calls = gh_call_log.read_text() if gh_call_log.exists() else ""
    return result


def test_start_named_agent_extraction_is_anchored_on_the_real_script():
    """Fail loudly if the script's layout drifts, instead of testing a stale/empty copy."""
    body = extract_function("start_named_agent")
    assert body.startswith("start_named_agent() {")
    assert body.endswith("\n}")
    assert "gh_in_progress_url_for_runner" in body
    assert "exit 2" in body


def test_env_unchanged_active_agent_is_left_alone(tmp_path):
    """Case 1: env_changed=0, service already `active` — no restart, no busy-check, rc=0.

    `systemctl is-active` itself is still invoked (that is how the function learns the state at
    all — it runs unconditionally before the `case`), so this only asserts that `restart` is never
    reached and the busy-check (`gh_in_progress_url_for_runner`) is never even called.
    """
    result = start_named_agent(2, 0, tmp_path, service_state="active")
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    assert result.restart_log == "", "systemctl restart must not be invoked"
    assert result.gh_calls == "", "the busy-check must not run when the .env did not change"


def test_env_changed_active_idle_agent_is_restarted(tmp_path):
    """Case 2: env_changed=1, active, agent IDLE — restart happens, on the right service."""
    result = start_named_agent(2, 1, tmp_path, service_state="active", in_progress_url="")
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    svc = f"{AGENT_SERVICE_PREFIX}-2.service"
    assert result.restart_log == f"restart {svc}\n"
    assert result.gh_calls == "autohostai-test-vm-2\n", "busy-check must run before restarting"


def test_env_changed_active_busy_agent_is_deferred_not_restarted(tmp_path):
    """Case 3: env_changed=1, active, agent BUSY — this is D4's whole point: rc=2, no restart,
    and the deferred message names the service so an operator can act on it later.
    """
    url = "https://github.com/acme/repo/actions/runs/123"
    result = start_named_agent(2, 1, tmp_path, service_state="active", in_progress_url=url)
    assert result.returncode == 2, f"stdout={result.stdout} stderr={result.stderr}"
    assert result.restart_log == "", "must NOT restart an agent with a job in flight (D4)"
    svc = f"{AGENT_SERVICE_PREFIX}-2.service"
    assert svc in result.stdout, "the deferred message must name the service"
    assert url in result.stdout, "the deferred message must name the in-progress run"


def test_env_changed_active_agent_gh_api_failure_defers_not_restarted(tmp_path):
    """Fix round (`sdd-security`, 2026-09-15): a GitHub API failure (expired token, 403/429,
    timeout — `gh_in_progress_url_for_runner` exits non-zero) must NOT be treated the same as
    "no job in flight". Before the fix, `|| true` collapsed both to an empty `url` and this case
    would have restarted a possibly-live agent; now it must defer (rc=2) exactly like the
    confirmed-busy case, never touching `systemctl restart`.
    """
    result = start_named_agent(2, 1, tmp_path, service_state="active", api_fails=True)
    assert result.returncode == 2, f"stdout={result.stdout} stderr={result.stderr}"
    assert result.restart_log == "", "an API failure must never be treated as 'idle'"
    svc = f"{AGENT_SERVICE_PREFIX}-2.service"
    assert svc in result.stdout, "the deferred message must name the service"


def test_env_changed_inactive_agent_goes_through_install_start_not_restart(tmp_path):
    """Case 4: env_changed=1, `failed`/`inactive` — the PRE-EXISTING install/start path, which
    this fix round must not have narrowed or broken while adding coverage for the new branch.
    """
    result = start_named_agent(2, 1, tmp_path, service_state="failed")
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    assert result.restart_log == "", "a never-started agent has nothing to restart"
    assert "svc.sh install actions-runner-2" in result.svc_log
    assert "svc.sh start" in result.svc_log
    assert result.gh_calls == "", "the busy-check is restart-only; install/start never needs it"


# --- FASE 2 registration-loop wiring: rc=2 is deferred, not a failure --------------------------

LOOP_START = 'for i in "${registered_idx[@]+"${registered_idx[@]}"}"; do'
LOOP_END = "done"


def test_registration_loop_extraction_is_anchored_on_the_real_script():
    body = extract_snippet(LOOP_START, LOOP_END)
    assert body.startswith(LOOP_START)
    assert 'start_named_agent "$i" "$env_changed"' in body
    assert "deferred_restart+=" in body
    assert "had_failure=1" in body


def run_registration_loop(rc_by_agent: dict) -> subprocess.CompletedProcess:
    """Drive the real FASE 2 registration-loop snippet with a stubbed `start_named_agent`.

    `start_named_agent` itself already has direct tests above, so here it is stubbed to return a
    fixed code per agent index — this isolates just the OUTER loop's classification of the three
    possible outcomes (ok / deferred / real failure), which is the specific wiring claim tasks.md
    makes: rc=2 must not count toward `had_failure`, and must land in `deferred_restart`.
    """
    indices = sorted(rc_by_agent)
    cases = "\n".join(f"        {i}) return {rc} ;;" for i, rc in rc_by_agent.items())
    program = "\n".join([
        "set -euo pipefail",
        f'ENV="{AGENT_ENV}"',
        f'SERVICE_PREFIX="{AGENT_SERVICE_PREFIX}"',
        'RUNNER_COUNT="3"',
        "had_failure=0",
        "deferred_restart=()",
        f"registered_idx=({' '.join(str(i) for i in indices)})",
        f"env_changed_idx=({' '.join(str(i) for i in indices)})",
        "start_named_agent() {",
        '    case "$1" in',
        cases,
        "    esac",
        "}",
        extract_snippet(LOOP_START, LOOP_END),
        'printf "had_failure=%s\\n" "$had_failure"',
        'printf "deferred_count=%s\\n" "${#deferred_restart[@]}"',
        'for d in "${deferred_restart[@]+"${deferred_restart[@]}"}"; do printf "deferred:%s\\n" "$d"; done',
    ])
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=30)


def test_deferred_restart_rc2_alone_does_not_count_as_had_failure():
    result = run_registration_loop({1: 0, 2: 2})
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    assert "had_failure=0" in result.stdout, "a deferred restart is not a failure"
    assert "deferred_count=1" in result.stdout
    assert "deferred:autohostai-test-vm-2" in result.stdout


def test_real_failure_rc_other_than_2_does_count_as_had_failure():
    result = run_registration_loop({3: 1})
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    assert "had_failure=1" in result.stdout, "a genuine start failure must still be reported"
    assert "deferred_count=0" in result.stdout
