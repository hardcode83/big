"""Suite of `runner-job-started.sh` (`ci-runner-workspace-pollution` R3).

The script is bash, installed standalone on the CI VM outside any checkout (see the script's own
header comment), so it is driven here via `subprocess.run` against real temporary directories —
not imported or mocked — using its override-argument mechanism (an optional first positional
argument, `WORK_DIR_OVERRIDE`) instead of self-location, exactly as the script's own docstring
says a test harness should.

Privileged-fixture limitation (read this before extending these tests): R3.3/D1's fix is a real
`chown -R` of root-owned files back to the agent user. Constructing a genuinely foreign-owned
(e.g. root-owned) fixture file requires privileges this sandboxed test environment does not have
— an unprivileged process cannot `chown` a file to a *different* owner. Two of the cases below
(`test_detected_and_chown_succeeds`, `test_chown_genuinely_fails`) therefore stub the external
`find`/`sudo` commands (via a `PATH` override, never by mocking the script itself) to force the
script's "something was found" branch deterministically and portably, and to pin the chown
outcome. This exercises the real control flow — detection message, chown invocation, logging,
exit code, `$RUNNER_HOME` naming — honestly, but NOT a genuine permission failure/success against
an actually-root-owned file. Running that genuine case requires a host where this test process
can actually create root-owned files under the target directory (e.g. running as root in a
container, or with real passwordless sudo) — not assumed here. `test_clean_tree_needs_no_action`
and the invalid-path cases use no stubs at all: they are fully genuine.
"""

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

HOOK = Path(__file__).with_name("runner-job-started.sh")
RUNNER_USER = os.environ.get("USER") or os.environ.get("LOGNAME") or "root"


def run_hook(work_dir, *, env=None):
    """Run the hook with an explicit override argument (never self-locating)."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(HOOK), str(work_dir)],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


def snapshot(tree: Path):
    """(relative path, uid, mode, mtime_ns) for every entry, to prove "nothing was modified"."""
    out = {}
    for p in sorted(tree.rglob("*")):
        st = p.lstat()
        out[str(p.relative_to(tree))] = (st.st_uid, stat.S_IMODE(st.st_mode), st.st_mtime_ns)
    return out


def make_stub_bin(
    tmp_path: Path,
    *,
    find_reports_foreign: bool,
    sudo_exit: int,
    find_exit: int = 0,
    stub_id: bool = False,
) -> Path:
    """A directory with stub `find`/`sudo`(/`id`) executables, to prepend onto PATH.

    `find` unconditionally reports one fake foreign-owned entry under its target (or nothing, if
    `find_reports_foreign` is False), and exits with `find_exit` (round 6: a non-zero `find_exit`
    with `find_reports_foreign=False` simulates a genuine `find` failure — as opposed to a
    genuine "nothing foreign, and find itself succeeded" clean tree, which the unstubbed
    `test_clean_tree_needs_no_action` already covers for real).
    `sudo` ignores its arguments and exits with `sudo_exit`, printing what it would have run —
    this is the injectable override the module docstring documents: it pins the chown outcome
    without needing real root, so the branch (not the privileged syscall) is what gets tested.
    `id` is stubbed only if `stub_id` is True, and always prints an empty line for `-un` — round
    6's guard against an empty `$(id -un)` reaching `find`'s `! -user` predicate.

    Round 11: `find` is stubbed for the D2 short-circuit call ONLY (its unique signature is the
    `-print -quit` it always carries) — the hook's second `find` invocation, that restores
    owner-write on restrictive directories after a successful chown, is left to run for REAL
    (delegated to the actual `find` binary, resolved before this directory is prepended onto
    PATH), so tests can exercise its genuine behavior instead of it silently no-op'ing under the
    same blanket stub.
    """
    bindir = tmp_path / "stubbin"
    bindir.mkdir()
    real_find = shutil.which("find")
    assert real_find, "no real `find` on PATH to delegate to"
    fake_output = 'echo "$1/FAKE_FOREIGN_FILE"' if find_reports_foreign else ""
    find_body = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        for arg in "$@"; do
            if [[ "$arg" == "-quit" ]]; then
                {fake_output}
                exit {find_exit}
            fi
        done
        exec {real_find} "$@"
        """)
    (bindir / "find").write_text(find_body)
    (bindir / "sudo").write_text(
        textwrap.dedent(f"""\
            #!/usr/bin/env bash
            echo "stub-sudo: $*" >&2
            exit {sudo_exit}
            """)
    )
    (bindir / "find").chmod(0o755)
    (bindir / "sudo").chmod(0o755)
    if stub_id:
        (bindir / "id").write_text("#!/usr/bin/env bash\necho ''\n")
        (bindir / "id").chmod(0o755)
    return bindir


# ── Clean tree: no writes, exit 0 (R3.4) ────────────────────────────────────────────────────


def test_clean_tree_needs_no_action(tmp_path):
    work = tmp_path / "_work"
    work.mkdir()
    (work / "checkout").mkdir()
    (work / "checkout" / "app.py").write_text("print('hi')\n")

    before = snapshot(work)
    result = run_hook(work)
    after = snapshot(work)

    assert result.returncode == 0, result.stderr
    assert after == before, "clean tree must not be modified at all"
    assert "clean" in result.stdout.lower() or "nothing to do" in result.stdout.lower()
    assert "chown" not in result.stdout.lower()


# ── Round 6 (`sdd-security`, 2026-09-15): a `find` failure must NOT be read as "clean" -------


def test_find_failure_is_not_treated_as_clean(tmp_path):
    """Before this fix, `FOUND="$(find ... || true)"` collapsed a genuine `find` error (e.g.
    permission denied descending into a subdirectory) into the same empty output as "nothing
    foreign" — silently skipping the chown and letting the job proceed into the EACCES this hook
    exists to prevent. Now: empty output is only "clean" when `find` itself also exited 0; a
    non-zero `find` with empty output must still trigger the chown.
    """
    work = tmp_path / "_work"
    work.mkdir()
    (work / "some_file.txt").write_text("content\n")

    stubbin = make_stub_bin(tmp_path, find_reports_foreign=False, find_exit=1, sudo_exit=0)
    env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

    result = run_hook(work, env=env)

    assert result.returncode == 0, result.stderr
    assert "already clean" not in result.stdout.lower(), (
        "an unconfirmed tree must never be logged with the genuine-clean message"
    )
    assert "chown" in result.stdout.lower(), "an unconfirmed tree must still be chowned, not skipped"


def test_empty_runner_user_does_not_act(tmp_path):
    """Round 6: `id -un` returning empty must not reach `find`'s `! -user` predicate at all."""
    work = tmp_path / "_work"
    work.mkdir()

    stubbin = make_stub_bin(tmp_path, find_reports_foreign=False, sudo_exit=0, stub_id=True)
    env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

    before = snapshot(work)
    result = run_hook(work, env=env)
    after = snapshot(work)

    assert result.returncode != 0, "an undetermined agent user must not silently proceed"
    assert after == before, "must not touch the tree without a confirmed owner to chown to"


# ── Invalid paths: R3.1 — validated, "no actúa", exit 0 -------------------------------------


def test_relative_path_does_not_act():
    result = run_hook("relative/_work")
    assert result.returncode == 0
    combined = (result.stdout + result.stderr).lower()
    assert "absolute" in combined


def test_nonexistent_path_does_not_act(tmp_path):
    ghost = tmp_path / "does-not-exist" / "_work"
    result = run_hook(ghost)
    assert result.returncode == 0
    combined = (result.stdout + result.stderr).lower()
    assert "not exist" in combined or "no exist" in combined


def test_path_not_ending_in_work_does_not_act(tmp_path):
    not_work = tmp_path / "some_other_dir"
    not_work.mkdir()
    before = snapshot(not_work)
    result = run_hook(not_work)
    after = snapshot(not_work)

    assert result.returncode == 0
    assert after == before
    combined = (result.stdout + result.stderr).lower()
    assert "_work" in combined


# ── Detection + chown, via stubbed find/sudo (see module docstring) -------------------------


def test_detected_and_chown_succeeds(tmp_path):
    work = tmp_path / "_work"
    work.mkdir()
    (work / "some_file.txt").write_text("owned by us for real, but 'find' is stubbed\n")

    stubbin = make_stub_bin(tmp_path, find_reports_foreign=True, sudo_exit=0)
    env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

    result = run_hook(work, env=env)

    assert result.returncode == 0, result.stderr
    assert "found" in result.stdout.lower()
    assert "chown" in result.stdout.lower()
    assert "succeeded" in result.stdout.lower()


def test_chown_success_also_restores_owner_write_on_restrictive_directories(tmp_path):
    """Round 11 (`sdd-security`, 2026-09-15): chown alone doesn't fix a directory whose MODE
    lacks owner-write (e.g. a `0555` a container process left behind) — `git clean -ffdx` still
    can't delete into it. `sudo`/`find` are stubbed the same way as the test above (chown itself
    can't be exercised unprivileged), but the mode-restoring `chmod` that now follows a
    successful chown is REAL, un-stubbed — this test constructs a genuinely restrictive,
    self-owned directory and confirms the hook actually flips its mode.
    """
    work = tmp_path / "_work"
    work.mkdir()
    restrictive = work / "readonly_dir"
    restrictive.mkdir(mode=0o555)
    assert not os.access(restrictive, os.W_OK), "fixture setup: must start genuinely unwritable"

    stubbin = make_stub_bin(tmp_path, find_reports_foreign=True, sudo_exit=0)
    env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

    result = run_hook(work, env=env)

    assert result.returncode == 0, result.stderr
    mode_after = stat.S_IMODE(restrictive.stat().st_mode)
    assert mode_after & stat.S_IWUSR, f"owner-write must be restored, mode is {oct(mode_after)}"


def test_restrictive_self_owned_directory_alone_is_not_reported_as_already_clean(tmp_path):
    """Round 12 (`sdd-security`, 2026-09-15): round 11's D2 short-circuit tested ownership only,
    so a `_work/` fully owned by the agent user but holding a self-owned `0555` directory took
    the "already clean" fast path and never reached the mode-restoring fix — a genuine bug in
    round 11's own fix, not a hypothetical. Fully genuine, no stubs at all: only ownership is
    already correct (this test process owns everything), so D2's OWN unstubbed `find` must be
    the one to catch the mode problem.
    """
    work = tmp_path / "_work"
    work.mkdir()
    restrictive = work / "readonly_dir"
    restrictive.mkdir(mode=0o555)
    try:
        result = run_hook(work)
        assert "already clean" not in result.stdout.lower(), (
            "a self-owned but mode-restrictive directory must not be reported as already clean"
        )
    finally:
        restrictive.chmod(0o755)  # restore before pytest's own tmp_path cleanup tries to rmtree it


def test_mode_fix_failure_fails_the_hook_instead_of_claiming_success(tmp_path):
    """Round 12 (`sdd-security`, 2026-09-15): the round-11 mode-restoring `find` piped its exit
    status and stderr to `2>/dev/null || true` — the exact fail-open shape the D2 fix (round 6)
    exists to prevent, just 40 lines later. A directory `find` cannot even `opendir()` into
    (mode `0000`) makes its own subtree unreachable and unfixed, and `find` reports that as a
    non-zero exit — which must now fail the whole hook loudly (like a genuine `chown` failure),
    not get swallowed into "chown ... succeeded". `find`/`sudo` are stubbed only for the D2 probe
    (to force entry into remediation deterministically); the mode-restoring `find` is real.
    """
    work = tmp_path / "_work"
    work.mkdir()
    unreadable = work / "unreadable_dir"
    unreadable.mkdir(mode=0o000)
    try:
        stubbin = make_stub_bin(tmp_path, find_reports_foreign=True, sudo_exit=0)
        env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

        result = run_hook(work, env=env)

        assert result.returncode != 0, (
            "an unconfirmed mode fix must fail the hook, not silently succeed: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert str(work) in (result.stdout + result.stderr), "the failure must name the affected tree"
    finally:
        unreadable.chmod(0o755)


def test_find_and_chown_stderr_are_sanitized_before_reaching_the_log(tmp_path):
    """Round 13 (`sdd-security`, 2026-09-15): the D2 `find` probe and `sudo -n chown -R` let
    their own stderr reach the job log unredirected — an attacker-influenced filename left under
    `_work/` by repository content (e.g. a fork PR) could surface in one of `find`'s or `chown`'s
    OWN diagnostic messages (e.g. "Permission denied: <name>") and inject ANSI/terminal escapes
    or forge a fake `runner-job-started:` log line into a LATER job's log — the same
    log/terminal-injection class `$FOUND_SAFE` already guards, on the two channels that guard
    never covered. Drives custom `find`/`sudo` stubs (not `make_stub_bin`, which has no hook for
    injecting attacker-controlled bytes) that each print a message containing a literal ESC byte
    to stderr, and confirms it never reaches the hook's own output unsanitized.
    """
    work = tmp_path / "_work"
    work.mkdir()

    stubbin = tmp_path / "stubbin"
    stubbin.mkdir()
    (stubbin / "find").write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        for arg in "$@"; do
            if [[ "$arg" == "-quit" ]]; then
                printf 'find: malicious \\x1b[31mINJECTED\\x1b[0m entry\\n' >&2
                echo "$1/FAKE_FOREIGN_FILE"
                exit 0
            fi
        done
        exec /usr/bin/find "$@"
        """))
    (stubbin / "sudo").write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        printf 'chown: malicious \\x1b[31mINJECTED\\x1b[0m entry\\n' >&2
        exit 0
        """))
    (stubbin / "find").chmod(0o755)
    (stubbin / "sudo").chmod(0o755)
    env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

    result = run_hook(work, env=env)

    combined = result.stdout + result.stderr
    assert "\x1b" not in combined, f"a raw ESC byte reached the log: {combined!r}"
    # tr replaces each ESC (0x1b) with '?' and leaves the surrounding printable bytes alone —
    # the exact expected shape, not just "no raw ESC" (which a *deleting* filter would satisfy
    # too, silently dropping the evidence instead of neutralizing it).
    assert "?[31mINJECTED?[0m" in combined, f"expected the neutralized-but-visible payload: {combined!r}"


def test_chown_genuinely_fails_names_runner_home(tmp_path):
    runner_home = tmp_path / "actions-runner-9"
    work = runner_home / "_work"
    work.mkdir(parents=True)
    (work / "some_file.txt").write_text("content\n")

    stubbin = make_stub_bin(tmp_path, find_reports_foreign=True, sudo_exit=1)
    env = {"PATH": f"{stubbin}:{os.environ['PATH']}"}

    result = run_hook(work, env=env)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    # Assert on the exact failure-message marker the script emits (`err`, ~line 143:
    # "... for RUNNER_HOME=$RUNNER_HOME — job will fail"), not just "runner_home appears somewhere
    # in the output". The D2 detection log line earlier ALWAYS prints $WORK_DIR (which contains
    # runner_home as a prefix), so a bare substring check on the whole combined output would pass
    # even if the actual chown-failure message dropped RUNNER_HOME entirely — proven by mutation:
    # removing "for RUNNER_HOME=$RUNNER_HOME" from the script's failure message left a naive
    # `str(runner_home) in combined` check green.
    assert f"for RUNNER_HOME={runner_home}" in combined, (
        "R3.5 requires the RUNNER_HOME to be named explicitly in the failure message"
    )


@pytest.mark.skipif(
    subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0,
    reason=(
        "this host has real passwordless sudo for the test user — the unstubbed case below "
        "would then unexpectedly succeed (sudo can chown regardless of current ownership), "
        "which is a different, genuinely-privileged scenario this suite does not assume"
    ),
)
def test_chown_genuinely_fails_without_stubs_when_sudo_has_no_password(tmp_path):
    """Same failure branch as above, but with a REAL (unstubbed) `sudo -n`.

    On a host without passwordless sudo configured for the test user (true for this sandbox,
    verified with `sudo -n true` during implementation: "sudo: a password is required"), the
    hook's real `sudo -n chown -R ...` call fails genuinely — not because the fixture file is
    foreign-owned (it isn't, `find` is still stubbed to force the "something to do" branch, per
    the module docstring), but because privilege escalation itself fails, which is a real
    instance of "the chown itself fails" (R3.5's premise), independent of any stub for `sudo`.
    """
    runner_home = tmp_path / "actions-runner-3"
    work = runner_home / "_work"
    work.mkdir(parents=True)
    (work / "some_file.txt").write_text("content\n")

    stubbin = make_stub_bin(tmp_path, find_reports_foreign=True, sudo_exit=0)  # sudo stub unused
    # Only override `find`; let the real `sudo` on PATH run.
    real_path = os.environ["PATH"]
    env = {"PATH": f"{stubbin.parent / 'find_only'}:{real_path}"}
    find_only = stubbin.parent / "find_only"
    find_only.mkdir()
    (find_only / "find").write_text((stubbin / "find").read_text())
    (find_only / "find").chmod(0o755)

    result = run_hook(work, env=env)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    # Same specific marker as test_chown_genuinely_fails_names_runner_home — see that test's
    # comment for why a bare `str(runner_home) in combined` is vacuous here.
    assert f"for RUNNER_HOME={runner_home}" in combined


# ── Self-location sanity (no override argument) ----------------------------------------------


def test_self_locates_two_dirs_up_from_hooks(tmp_path):
    """Installed layout: $RUNNER_HOME/hooks/runner-job-started.sh, targets $RUNNER_HOME/_work."""
    runner_home = tmp_path / "actions-runner-7"
    hooks_dir = runner_home / "hooks"
    hooks_dir.mkdir(parents=True)
    work = runner_home / "_work"
    work.mkdir()
    (work / "f.txt").write_text("x\n")

    installed = hooks_dir / "runner-job-started.sh"
    installed.write_text(HOOK.read_text())
    installed.chmod(0o755)

    result = subprocess.run(
        ["bash", str(installed)],  # no override argument: must self-locate
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert str(work) in result.stdout
