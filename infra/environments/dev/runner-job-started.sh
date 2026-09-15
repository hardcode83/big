#!/usr/bin/env bash
# ACTIONS_RUNNER_HOOK_JOB_STARTED for AutoHostAI's self-hosted GitHub Actions runner pool.
#
# Why this exists: docker-compose.yml's services bind-mount the repo tree and (some) run as
# root, writing root-owned files into what is, on the CI VM, the runner's persistent `_work/`.
# `actions/checkout` (clean: true) cannot delete root-owned files there and fails with EACCES
# in step 0, before any workflow step runs — nothing IN the workflow can react to that failure.
# This hook returns `_work/` to a state `actions/checkout` CAN clean, before checkout runs.
# See sdd/changes/ci-runner-workspace-pollution/proposal.md (R3) and design.md (D1/D2).
#
# Installed by `runner-bootstrap.sh` (section 4 of this change) at, per agent `i`:
#   $RUNNER_HOME/hooks/runner-job-started.sh   (e.g. /opt/actions-runner-2/hooks/runner-job-started.sh)
# and declared via $RUNNER_HOME/.env: ACTIONS_RUNNER_HOOK_JOB_STARTED=<that absolute path>.
#
# GitHub's hook contract (verified against GitHub's docs during design):
#   - On Linux, the runner invokes this script via `bash -e <path>` (falls back to `sh`).
#     A NON-ZERO EXIT CODE FAILS THE JOB.
#   - There is no timeout for job-started hooks — GitHub's docs recommend the script add its
#     own timeout handling if it might hang. This is why the D2 short-circuit below is a
#     read-only `find ... -print -quit`: it must stay fast on a clean tree, since nothing else
#     bounds this script's running time.
#   - GITHUB_WORKSPACE / RUNNER_WORKSPACE are not documented for job-started hooks specifically
#     — this script does NOT rely on any such env var. It self-locates instead (see below).
#
# This script's own exit-code decision (so sections 4/6 and the hook's own log agree on it):
#   - A VALIDATION failure (WORK_DIR not absolute / doesn't exist as a directory / doesn't
#     end in `/_work`) is logged and the script exits 0 WITHOUT acting. This "no actúa" behavior
#     follows task 3.1's own description ("...; si la validación falla, no actúa") together with
#     R3.6 ("THE SYSTEM SHALL acotar la actuación del hook al `_work/` del agente que lo ejecuta,
#     y NOT actuar sobre el de otro agente ni sobre rutas fuera de él" — the closest EARS
#     requirement in spirit to "don't act on an unrecognized/invalid path"). It is NOT what R3.1's
#     own EARS text says: R3.1 is only "THE SYSTEM SHALL versionar en el repositorio un script de
#     hook de inicio de job, bajo `infra/environments/dev/`" — purely about versioning the file,
#     silent on validation-failure behavior. An overly strict validator that fails real jobs over
#     a path edge case would be exactly the kind of fragility this change is trying to remove.
#   - A `chown` that genuinely fails on a path that DID validate exits NON-ZERO (R3.5: the job
#     should fail loudly here, naming $RUNNER_HOME, rather than silently proceed into a
#     checkout that will EACCES anyway).
#
# Usage: runner-job-started.sh [WORK_DIR_OVERRIDE]
#   No arguments (real installed usage): self-locates $RUNNER_HOME two directories up from this
#   script's own resolved path (.../hooks/runner-job-started.sh -> .../hooks -> $RUNNER_HOME)
#   and targets $RUNNER_HOME/_work.
#   One positional argument: used as WORK_DIR verbatim instead of self-locating. This exists so
#   infra/environments/dev/test_runner_job_started.py can drive this script against a real
#   temporary directory instead of the (nonexistent, in a test sandbox) installed layout.
#   Still subject to the same R3.1 validation as the self-located path.
#
# Deliberately self-contained: no dependency on the rest of this repo's Python tooling — this
# has to run standalone on the VM from $RUNNER_HOME/hooks/, outside any checkout.

set -uo pipefail
# NOT `set -e`: R3.1's validation failure must exit 0 (see above), so the validation is a plain
# `if`, never a bare failing command that `-e` would trip. Every other fallible command below is
# guarded explicitly and its exit status handled on purpose.

log() {
    printf 'runner-job-started: %s\n' "$1"
}

err() {
    printf 'runner-job-started: %s\n' "$1" >&2
}

# --- Resolve WORK_DIR: explicit override (tests) or self-location (real usage) -------------
if [[ $# -ge 1 ]]; then
    WORK_DIR="$1"
else
    script_path="${BASH_SOURCE[0]:-$0}"
    script_dir="$(cd -- "$(dirname -- "$script_path")" >/dev/null 2>&1 && pwd -P)"
    hooks_dir="$script_dir"
    runner_home_self_located="$(dirname -- "$hooks_dir")"
    WORK_DIR="$runner_home_self_located/_work"
fi

# RUNNER_HOME for logging (R3.5 wants it named explicitly on chown failure): the parent of
# WORK_DIR. Computed uniformly for both the self-located and override cases — after validation,
# WORK_DIR is guaranteed to end in `/_work`, so this is exactly $RUNNER_HOME either way.
RUNNER_HOME="$(dirname -- "$WORK_DIR")"

# --- Task 3.1 / R3.6: validate before touching anything ---------------------------------------
# Absolute, exists as a directory, ends in `/_work`. On failure: log why, exit 0 (does not act
# — see the exit-code note above; that behavior comes from task 3.1's description and R3.6, not
# from R3.1's own EARS text). This is a plain `if`, not a command left to trip `set -e`.
validation_failed=0
if [[ "$WORK_DIR" != /* ]]; then
    err "WORK_DIR '$WORK_DIR' is not an absolute path — not acting"
    validation_failed=1
elif [[ "$WORK_DIR" != */_work ]]; then
    err "WORK_DIR '$WORK_DIR' does not end in '/_work' — not acting"
    validation_failed=1
elif [[ ! -d "$WORK_DIR" ]]; then
    err "WORK_DIR '$WORK_DIR' does not exist as a directory — not acting"
    validation_failed=1
fi

if [[ "$validation_failed" -eq 1 ]]; then
    exit 0
fi

# --- R3.6: scope is this WORK_DIR only, nothing else ------------------------------------------
# (Enforced structurally: every find/chown below is rooted at $WORK_DIR. In REAL usage — no
# arguments, GitHub's own invocation contract — self-location guarantees $WORK_DIR is this
# agent's own `_work/`, since each agent has its own installed copy of this script at its own
# path. The one-argument WORK_DIR_OVERRIDE form (test-only, see the header comment) does NOT
# carry that guarantee: validation above only checks the path is absolute, exists, and ends in
# `/_work` — not that it belongs to the caller. This is not a privilege escalation as written
# (anyone who can invoke this script with an argument is already the agent user with the pool's
# NOPASSWD sudo grant), but it means "self" only holds for the self-located branch, not the
# override — corrected here after the previous version of this comment overclaimed it for both,
# round 7, panel de `/sdd:review`, `sdd-security`, 2026-09-15.)

RUNNER_USER="$(id -un)"
if [[ -z "$RUNNER_USER" ]]; then
    # `id -un` returning empty would make `! -user ""` an invalid `find` predicate below — fail
    # loudly rather than let that reach `find` and be misread as some other outcome (round 6,
    # panel de `/sdd:review`, `sdd-security`, 2026-09-15).
    err "id -un returned empty for RUNNER_HOME=$RUNNER_HOME — cannot determine the agent's own user, not acting"
    exit 1
fi

# --- D2 short-circuit: read-only, must stay fast on a clean tree ------------------------------
# First entry that is EITHER not owned by $RUNNER_USER OR a directory lacking owner-write, or
# empty if the tree is already clean by both measures. Round 11 added the mode-restoring chmod
# below (a directory a container left `0555`/`0500` blocks `git clean` exactly like wrong
# ownership does) but only wired it behind the ownership probe — a tree fully owned by
# $RUNNER_USER yet still holding a restrictive-mode directory took this "already clean" branch
# and never reached the fix, contradicting the very claim this log line makes (round 12, panel de
# `/sdd:review`, `sdd-security`, 2026-09-15: "ya lo está" tested ownership, not "borrable" — the
# spec's actual promise). The two conditions share one `-print -quit` probe, not two `find`
# calls, to keep the fast path fast (this hook has no timeout — see the header comment).
# `find`'s own exit status is captured SEPARATELY from its output (round 6 fix): before that,
# `|| true` collapsed "find genuinely failed partway through" (e.g. permission denied descending
# into some subdirectory) into the exact same empty `$FOUND` as "genuinely nothing to flag" — so
# a real find error would have been logged and treated as "already clean" and let the job proceed
# into the EACCES this hook exists to prevent. Now: empty output AND rc=0 is the only "clean"
# verdict; empty output with rc!=0 is NOT confirmed clean and falls through to chown anyway
# (still bounded and non-destructive, and the only action that actually satisfies R3.3 without a
# positive confirmation). find's own diagnostics (if any) are captured and sanitized, NOT left to
# reach stderr unredirected (round 13, panel de `/sdd:review`, `sdd-security`, 2026-09-15): a
# diagnostic naming an attacker-influenced path (`checkout`'d repo content, e.g. from a fork PR)
# could otherwise inject ANSI/terminal escapes or forge fake `runner-job-started:` log lines in
# THIS job's own log — the same log/terminal-injection class `$FOUND_SAFE` below already guards,
# extended to the channel that guard didn't cover.
find_rc=0
find_err_file="$(mktemp)"
FOUND="$(find "$WORK_DIR" \( ! -user "$RUNNER_USER" -o \( -type d ! -perm -u+w \) \) -print -quit 2>"$find_err_file")" || find_rc=$?
find_err="$(cat "$find_err_file")"
rm -f "$find_err_file"
if [[ -n "$find_err" ]]; then
    find_err_safe="$(printf '%s' "$find_err" | tr '\000-\037\177' '?')"
    err "find over $WORK_DIR reported: $find_err_safe"
fi

if [[ -z "$FOUND" && "$find_rc" -eq 0 ]]; then
    log "$WORK_DIR is already clean (every entry owned by $RUNNER_USER, every directory owner-writable) — nothing to do"
    exit 0
fi

# --- D1 fix: chown -R the OWN _work/ back to the agent user (never destructive) ---------------
if [[ -n "$FOUND" ]]; then
    # Sanitize $FOUND before it ever reaches a log line. $WORK_DIR is populated by
    # `actions/checkout` of repository content, which can include attacker-influenced filenames
    # (e.g. from a fork PR) — an unsanitized path here would let a maliciously-named entry inject
    # ANSI/terminal escape sequences or embedded newlines that spoof/fabricate fake log lines in
    # this hook's own output (log/terminal injection). Replace every ASCII control character
    # (0x00-0x1F, including ESC/`\x1b`, and 0x7F) with `?` — this also neutralizes embedded
    # CR/LF, so one `find` result can't masquerade as multiple log lines. Kept dependency-free
    # (`tr`, no repo Python tooling here).
    FOUND_SAFE="$(printf '%s' "$FOUND" | tr '\000-\037\177' '?')"
    log "found a non-deletable entry under $WORK_DIR (e.g. '$FOUND_SAFE', foreign-owned or a restrictive-mode directory) — chown -R to $RUNNER_USER and restoring directory permissions"
else
    log "find over $WORK_DIR exited non-zero (rc=$find_rc) before confirming the tree is deletable — NOT treating as clean, chown -R and permission restore anyway"
fi

# `-n` (non-interactive): the pool's sudoers grant (`%ci-agents ALL=(ALL) NOPASSWD:ALL`, see
# runner-bootstrap.sh) already makes this passwordless in real usage, so `-n` changes nothing
# there — it exists so a mis-provisioned host (sudo unexpectedly asking for a password) fails
# fast into the R3.5 branch below instead of hanging with no timeout (see the contract note
# above) waiting on a prompt nobody can answer.
#
# stderr captured and sanitized, not left to reach the job log unredirected (round 13, same
# log/terminal-injection motive as the D2 probe above): `chown -R` can print a per-file error
# line naming an attacker-influenced path even on individual failures within an overall success,
# and unconditionally on a genuine failure.
chown_err="$(sudo -n chown -R "$RUNNER_USER" "$WORK_DIR" 2>&1 1>/dev/null)"
chown_rc=$?
if [[ -n "$chown_err" ]]; then
    chown_err_safe="$(printf '%s' "$chown_err" | tr '\000-\037\177' '?')"
    err "chown -R $WORK_DIR to $RUNNER_USER reported: $chown_err_safe"
fi
if [[ "$chown_rc" -eq 0 ]]; then
    log "chown -R $WORK_DIR to $RUNNER_USER succeeded"
    # R3.3 covers more than ownership: a directory whose MODE lacks owner-write blocks
    # `actions/checkout`'s `git clean -ffdx` just as surely as wrong ownership does — chown alone
    # doesn't fix a 0555/0500 directory a container process left behind (round 11, panel de
    # `/sdd:review`, `sdd-security`, 2026-09-15). Safe to run without `sudo`: chown above just
    # made `$RUNNER_USER` the owner, and a file's owner can always chmod their own file
    # regardless of its current mode. Bounded to `$WORK_DIR`; directories only (files need no
    # execute bit to be deleted, and touching an unrelated regular file's mode could change
    # behavior a job expects unmodified).
    #
    # Its own exit status and stderr are captured, NOT `2>/dev/null || true` (round 12, panel de
    # `/sdd:review`, `sdd-security`, 2026-09-15: the round-11 version reintroduced the exact
    # fail-open shape the D2 fix above exists to prevent — a directory `find` can't even
    # `opendir()` into, e.g. mode `0000`, makes the whole subtree below it unreachable and unfixed,
    # `find` exits non-zero, and `2>/dev/null || true` swallowed both the status and the
    # diagnostic, so the hook printed "succeeded" and exited 0 over a tree that was still not
    # actually deletable). A genuine failure here is treated exactly like a genuine chown failure:
    # exit non-zero, name RUNNER_HOME, let the job fail loudly instead of proceeding into the
    # EACCES this hook exists to prevent.
    mode_fix_err="$(find "$WORK_DIR" -type d ! -perm -u+w -exec chmod u+rwx {} + 2>&1)"
    mode_fix_rc=$?
    if [[ "$mode_fix_rc" -ne 0 ]]; then
        mode_fix_err_safe="$(printf '%s' "$mode_fix_err" | tr '\000-\037\177' '?')"
        err "restoring directory permissions under $WORK_DIR FAILED (rc=$mode_fix_rc) for RUNNER_HOME=$RUNNER_HOME: $mode_fix_err_safe — job will fail"
        exit 1
    fi
    exit 0
else
    err "chown -R $WORK_DIR to $RUNNER_USER FAILED (rc=$chown_rc) for RUNNER_HOME=$RUNNER_HOME — job will fail"
    exit 1
fi
