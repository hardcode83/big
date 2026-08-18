"""The enumeration of unscoped reads is a set of callers, not a paragraph (design D9).

The system's cross-tenant reads used to be counted in prose, in the docstring of
`SqlAlchemyUserRepository.find_by_email_globally`, which four specs cited as "the one place
that count is stated". It went stale three times: it said "THE ONLY" until `guest-portal-api`
added a second, then "THE TWO" twice over in parallel branches, and it was still saying
"ONE OF THE THREE" while `locate_without_tenant_scoping` had made it four. It was **five** all
along: the review panel of `rule11-ownership-single-source` found `find_by_token_hash` outside
the count, which is the fourth time that numeral was wrong and the reason it is no longer written
anywhere a human maintains it.

That count is the audit control for rule 1 of `steering/security.md`, so it stops being prose
here. The set of callers of `require_unmarked_session` is the census of one class of read: the
ones where an anonymous caller presents a credential and the row itself resolves the tenant.
Asserted below against the five declared — adding a caller without declaring it is red,
removing a call is red.

**What this census is NOT is a list of every query in the system that runs without a tenant**,
and that limit is stated here because the version of this docstring that shipped first claimed
otherwise. `test_what_this_census_does_not_catch` names the reads that live outside it.

Static analysis in its own module, next to `test_session_marking.py` and `test_layering.py`,
which enforce their invariants the same way, meta-test included.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

GUARD = "require_unmarked_session"

#: `core/db.py` DEFINES the guard; it is not one of the reads it protects.
GUARD_OWNER = Path("core/db.py")

#: The unscoped reads of the system, as (module relative to `app/`, function).
#:
#: Each one is here for the same structural reason: an anonymous caller presents a credential
#: — an address, a token, a photo id — and the row is what resolves the tenant, so there is
#: nothing to filter by when the query runs.
DECLARED_UNSCOPED_READS = frozenset(
    {
        ("auth/infrastructure/repositories.py", "find_by_email_globally"),
        ("auth/infrastructure/repositories.py", "consume_globally"),
        ("guests/infrastructure/portal_repositories.py", "find_live_by_token_hash"),
        ("cleaning/infrastructure/repositories.py", "locate_without_tenant_scoping"),
        # The fifth, and the reason this set is five and not four: the review panel of
        # `rule11-ownership-single-source` found it outside the census while three prose sites
        # claimed the census WAS the class. An incoming webhook carries no JWT, so the row
        # resolves the tenant — structurally identical to the portal's token lookup above.
        ("integrations/infrastructure/repositories.py", "find_by_token_hash"),
    }
)


#: Reads that require an unmarked session and do NOT call the guard, both in
#: `integrations/infrastructure/repositories.py`. Named so the census's green cannot be read as
#: covering every query in the system that runs without a tenant; see
#: `test_what_this_census_does_not_catch` for why they are outside.
#:
#: `find_by_token_hash` was here too until the review panel established it was the SAME class as
#: the declared reads rather than a different one. It is now guarded and declared above — which
#: is the outcome this set exists to force: an entry is either a different class with a written
#: reason, or a gap someone closes.
KNOWN_UNGUARDED_UNMARKED_READS = frozenset({"select_pending", "lease"})


def _app_modules() -> list[Path]:
    return sorted(path for path in APP_ROOT.glob("**/*.py") if path.relative_to(APP_ROOT) != GUARD_OWNER)


def _calls_the_guard(node: ast.AST) -> bool:
    """Whether this expression is a call to the guard, written either way.

    Both spellings count: `require_unmarked_session(...)` after a `from … import`, and
    `db.require_unmarked_session(...)` after `from app.core import db`. Matching only the
    first would leave a hole exactly where it hurts — a fifth read written the second way
    would be correctly GUARDED and yet invisible here, so it would be neither `undeclared`
    nor `missing`, and would ship unaudited. That is the drift this file exists to end.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == GUARD
    return isinstance(func, ast.Attribute) and func.attr == GUARD


def _guard_callers(tree: ast.Module) -> set[str]:
    """The names of the functions whose body calls the guard.

    Matched on the enclosing `def`, not on the call's line, because what the census names is
    the READ — and a call attributed to a line number would have to be re-checked every time
    something above it moved.
    """
    callers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(_calls_the_guard(inner) for inner in ast.walk(node)):
            callers.add(node.name)
    return callers


def _observed_unscoped_reads() -> set[tuple[str, str]]:
    observed: set[tuple[str, str]] = set()
    for module_path in _app_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        relative = str(module_path.relative_to(APP_ROOT))
        observed.update((relative, name) for name in _guard_callers(tree))
    return observed


def test_the_unscoped_reads_are_exactly_the_declared_ones() -> None:
    observed = _observed_unscoped_reads()

    undeclared = observed - DECLARED_UNSCOPED_READS
    missing = DECLARED_UNSCOPED_READS - observed

    assert not undeclared, (
        "these call `require_unmarked_session` without being declared in "
        f"DECLARED_UNSCOPED_READS: {sorted(undeclared)}. An unscoped read is a cross-tenant "
        "read, which is the audit control for rule 1 of steering/security.md — declare it "
        "here, with an isolation test of its own, or scope the query."
    )
    assert not missing, (
        f"these are declared as unscoped reads but no longer call the guard: {sorted(missing)}. "
        "Either the read is gone, in which case drop it from DECLARED_UNSCOPED_READS, or the "
        "call was removed and the read is now silently tenant-scoped on a marked session."
    )


def test_there_are_app_modules_to_check() -> None:
    # Guards against the whole file passing because the glob matched nothing, exactly as
    # `test_session_marking.py` does for its own scan.
    assert len(_app_modules()) > 50


def test_the_scan_finds_a_caller_and_ignores_what_it_should() -> None:
    """The enforcement mechanism gets its own test, like its two neighbours'."""
    assert _guard_callers(
        ast.parse("async def read_it(self):\n    require_unmarked_session(self._s, read='x')")
    ) == {"read_it"}

    # Nested inside a conditional or a `with` still counts: the scan walks the whole body.
    assert _guard_callers(
        ast.parse("def read_it(s):\n    if s:\n        require_unmarked_session(s, read='x')")
    ) == {"read_it"}

    # Called through the module rather than imported by name — the spelling that would
    # otherwise be guarded, undeclared and invisible at once.
    assert _guard_callers(
        ast.parse("def read_it(s):\n    db.require_unmarked_session(s, read='x')")
    ) == {"read_it"}

    # A module that merely imports or re-exports the name is not a read.
    assert _guard_callers(ast.parse("from app.core.db import require_unmarked_session")) == set()
    assert _guard_callers(ast.parse("def f():\n    return require_unmarked_session")) == set()


def test_what_this_census_does_not_catch() -> None:
    """R3.4's obligation, applied to this guard: say what the green does not cover.

    **First, and measured rather than hypothetical: two reads that require an unmarked session
    exist today and are deliberately not in the census above.** Both are in
    `app/integrations/infrastructure/repositories.py`:

    `select_pending` and `lease` MUST run unmarked because `webhook_events.tenant_id` is
    nullable and a marked session hides `tenant_id IS NULL` rows *without erroring* — the same
    silent failure this guard exists to convert into a `raise`. They are a **different class**
    from the five above: nothing about them resolves a tenant, they drain a queue that
    deliberately holds unattributed rows, so "was this session marked?" is not the question that
    protects them. `scheduler/tasks.py` opens their session unmarked, and `test_tenant_filter.py`
    pins it (`test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`) — the
    invariant is held by a test, just not by this one.

    **The history matters more than the list, because it is what the list is for.** This
    docstring first called the residual "a **fifth** unscoped read that is entirely new", which
    was false in the way that counts: the fifth already existed. It was `find_by_token_hash`, in
    this same module. Naming it as merely hypothetical is what let a green here read as coverage
    of every unscoped read in the system, and the review panel caught it. It was then listed here
    as a known gap — and a gap that is listed is a gap someone can close, which is what happened:
    it is guarded and declared above. The residual list earns its place by being the thing that
    makes an omission actionable, not by being complete.

    Beyond those two, the residual is a genuinely new read that neither calls the guard nor
    appears above. Nothing here can reclaim it: the scan is anchored on the guard, so a `select`
    with no `tenant_id` written from scratch in an adapter is invisible to it.

    What is NO LONGER a residual, because the security panel of section 1 found it: a read that
    calls the guard as `db.require_unmarked_session(...)` instead of by imported name. That one
    was guarded and yet invisible — neither undeclared nor missing — so it could have shipped
    unaudited. `_calls_the_guard` now matches both spellings, and the case is pinned above.

    Still uncovered, and worth naming for the same reason: a caller that reaches the guard
    through an alias (`g = require_unmarked_session; g(...)`) or a wrapper of its own; and a
    SECOND guarded read that shares both its module and its method name with a declared one
    (a different class, same method name), which the existing entry absorbs — the census is
    keyed on `(module, function name)`, not on the class. No such collision exists today; the
    five declared names are distinct.

    The naming convention does not close it either, and that is measured rather than assumed:
    `*_globally` is already non-exhaustive, because **most** of the declared reads do not carry
    the suffix — the portal's, `cleaning`'s and `integrations`'. Two specs say so, and the third
    is the one that spent two changes outside the census: a convention that names only the
    `*_globally` pair is not a search you can trust to find the rest.

    No count in that paragraph, deliberately, and the reason is worth keeping because it is
    subtle: the assertion below pins the *unsuffixed names*, not how many reads there are. A sixth
    read called `*_globally` would be added to `DECLARED_UNSCOPED_READS`, leave `unsuffixed`
    byte-identical, and keep the suite green while any "N of M" written here went false. The
    numerator is defended; a denominator would not be.

    What does cover it is a human reading the diff: any `select` without a tenant clause in an
    adapter is visible in review, and the tenancy panel has it on its list. This test exists so
    that its green is not read as more than it is.
    """
    unsuffixed = {read for _, read in DECLARED_UNSCOPED_READS if not read.endswith("_globally")}

    assert unsuffixed == {
        "find_live_by_token_hash",
        "locate_without_tenant_scoping",
        "find_by_token_hash",
    }

    # The reads named above are pinned, not just described. A docstring that lists them
    # would go stale the moment one is guarded or renamed — which is the pathology this whole
    # change exists to end, so the disclosure gets the same treatment as the census itself.
    outside = KNOWN_UNGUARDED_UNMARKED_READS
    module = APP_ROOT / "integrations/infrastructure/repositories.py"
    source = module.read_text(encoding="utf-8")
    functions = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = outside - functions
    assert not missing, (
        f"{sorted(missing)} no longer exist in {module.name}. This test names them as reads that "
        "require an unmarked session and do NOT call the guard; if they were renamed or removed, "
        "update the residual in this docstring so it keeps describing the tree that exists."
    )
    guarded = _guard_callers(ast.parse(source))
    newly_guarded = outside & guarded
    assert not newly_guarded, (
        f"{sorted(newly_guarded)} now call the guard, so they belong in "
        "DECLARED_UNSCOPED_READS and must come out of this residual. The census and the list of "
        "what it omits cannot both claim them."
    )
