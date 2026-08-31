"""Suite of `rule11-ownership.py`: the guard's own meta-tests.

Ported from `backend/tests/test_rule11_ownership.py`, which this change deletes, plus what the
move made newly possible to get wrong: a `SCOPE` that resolves to nothing, an exemption that
outlives the file it exempts, and an authority whose prose stops describing the scope it
declares.

The obligation of method these tests carry: **a green must mean "it looked at this"**. A guard
that walks zero files and reports zero offenders is the silent failure, so every entry point
here has a case that proves the red.
"""

import importlib.util
import re
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "rule11_ownership",
    Path(__file__).with_name("rule11-ownership.py"),
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)

GuardError = module.GuardError
Kind = module.Kind
ScopeEntry = module.ScopeEntry
SCOPE = module.SCOPE
ROOT = module.REPO_ROOT


def offending(text, *, python=False):
    return module._offending_blocks(text, python=python)


# ── The scan still does what it claims ─────────────────────────────────────────────────────


def test_the_prose_tree_is_actually_visible() -> None:
    """Fail-closed, and never `skip`.

    Inherited from the container era, where a bind mount whose source was missing arrived as an
    empty directory. On the host the shape is a shallow or partial checkout and the failure is
    identical: the scan walks nothing and reports success. `skip` would be almost as bad — in
    `-rs` output it reads as "did not apply", which is exactly the wrong thing for a security
    control to say when its input has vanished.
    """
    scanned = module.check_tree_is_visible(SCOPE, ROOT)
    assert scanned >= module.MINIMUM_MARKDOWN_FILES


def test_no_block_outside_the_table_declares_who_writes_a_sink() -> None:
    reported = module.offenders(SCOPE, ROOT)
    assert not reported, module.render(reported)


def test_the_scan_catches_what_it_claims_to() -> None:
    """The enforcement mechanism gets its own test, like its two neighbours'.

    All four positives name a real census column, so they keep firing after the sink axis lost
    its meta-vocabulary: what came out was `regla 11`, `rule 11`, `censo` and the two names of
    the mechanism, none of which any of these four depends on.
    """
    both_axes = "`audit_logs.changes` is one of them, and this change is its first writer."
    assert offending(both_axes)

    # Split across two lines of one bullet — copy number eight's exact shape.
    split = "- declara `messages.content` en el censo de la regla 11,\n  con esta capability como primer escritor vivo."
    assert offending(split)

    # One axis only: neither is reportable.
    assert not offending("`conversations` has its first writer here.")
    assert not offending("`audit_logs.changes` is a cleartext sink; see rule 11.")

    # Two different paragraphs are two blocks, which is the documented residual below.
    assert not offending(
        "`audit_logs.changes` is a cleartext sink.\n\nThis change is its first writer."
    )

    # Python docstrings and comment runs, not code.
    assert offending('"""`messages.intent` — rule 11. First writer: us."""', python=True)
    assert offending(
        "# `notification_logs.body` is a rule 11 sink\n# and access-notifications is its first writer",
        python=True,
    )


def test_the_meta_vocabulary_alone_is_no_longer_a_sink() -> None:
    """D3, and the shape it was measured on.

    The three blocks that put `main` in the red — `sdd/specs/access-notifications.md:372`, `:525`
    and `:689` — matched the sink axis through the word `censo` and through nothing else. They
    attribute members of the `NotificationType` enum, whose authority is that spec plus
    `backend/tests/notifications/test_writer_census.py`, not a column this table governs. A text
    *about* the guard is not a duplicated attribution of anything.
    """
    assert not offending("Cuatro tipos siguen sin escritor en el censo de esta capacidad.")
    assert not offending("Rule 11 says the first writer inherits the contract.")
    # And the axis still fires when a real column is present alongside the meta-vocabulary.
    assert offending("`audit_logs` es un sumidero de la regla 11 y su escritor vivo es éste.")


def test_what_this_guard_does_not_catch() -> None:
    """R2.3: say what the green does not cover, so it is not read as completeness.

    (The requirement that governs this test is R2.3, which is what asks for the measured cost of
    an exclusion to be registered here. R3.4 governs item 8 alone — the enum-member decision.)

    Every item is a shape that exists in the tree today or that defeated an earlier version of
    a sibling guard — not a list of good intentions. **Every count below was recounted against
    the tree on 2026-08-31, not carried forward**: the previous version of this docstring said
    "36 blocks" and "about sixteen", and both had gone stale.

    1. **Paraphrase.** An attribution with none of the ownership vocabulary ("esta capability
       estrena la columna", "desde aquí se rellena") is invisible. The axis is a vocabulary,
       not a semantic analyser. The section 2 panel of `rule11-ownership-single-source` found a
       paraphrased copy that a literal grep could not see, so this is measured, not
       hypothetical.
    2. **Split across two blocks** — the column in one paragraph, the owner in the next. The
       block closes the two-contiguous-lines case, not the two-paragraph one.
    3. **A column not yet in the census.** The sink axis is fed by the table, so column number
       twenty-two is invisible until it is declared there. That is the same blindness
       `webhook_events.event_type` had for two changes.
    3b. **`incidents` or `messages` named as a bare table**, without one of their columns. The
       other four census tables are matched by name; those two are common English words and
       would fire on unrelated prose, so they are matched only at column level. A real case of
       this shape exists today and is deliberately left unreported:
       `app/audit/domain/actions.py` says the guest portal "was the first writer of
       `incidents`" — which is about rule 9's audit actions, not about who owns a rule 11 sink.
    4. **The `app/cli/seed_demo.py` hole** in the `maintenance` free-text guard
       (`security.md`): out of scope by that proposal's decision, and named here rather than
       left for the green to imply.
    5. **The out-of-census trees and the declared exceptions of `SCOPE`**, and the magnitude is
       worth stating rather than implying. Recounted 2026-08-31: `sdd/changes/` holds **38
       blocks that fire both axes**, and **all thirty-eight are frozen under `archive/`** —
       including `2026-08-01-user-management/proposal.md`, which still carries verbatim the
       "primer escritor real de `audit_logs`" sentence the sweep removed from
       `sdd/specs/user-management.md`. The exclusion is right (a change record is the same
       document before and after the `mv`), but it means the largest prose corpus in the
       repository is exempt from the thesis that prose cannot be made to stay true. That is a
       measured concession, not a formality. `docs/adr/` holds **0**, as it did when it was
       excluded: immutability is its whole motive, not a block count.
    5b. **The roadmap trees**, `sdd/roadmap.md` and `sdd/roadmap/**`, excluded by this change.
       Measured cost 2026-08-31: **0 blocks** fire both axes across the eighty-six documents of
       that tree — **1** did before the sink axis lost its meta-vocabulary, and that one was
       `sdd/roadmap/rule11-ownership-single-source.md`, the file this change stops exempting by
       name because the exclusion now covers it. The exclusion is not bought by that zero: a
       roadmap entry **declares work not done**, so saying a column has no writer yet is its
       function. Without it, a roadmap entry forces an edit to a shared file to unblock somebody
       else's merge gate.

       **And it costs more than the two exclusions it sits beside, which is worth saying plainly
       rather than leaving to the analogy.** `docs/adr/` is immutable by convention and
       `sdd/changes/archive/` is frozen by the `mv`, so what they exempt stops changing. Roadmap
       notes do not: they are edited after the work they describe has shipped. So an attribution
       written into `sdd/roadmap/<x>.md` — "`audit_logs.changes` la heredará esta entrada: será su
       primer escritor vivo" — fires both axes when scanned and is exempt **permanently**,
       including after that writer becomes real, which is exactly the "quién heredará" case rule
       11 exists to redden. The exclusion is required by R2.2 and was resolved with the change's
       owner (OQ3); this is its price, recorded here because the green must not imply it away.
       And the price is not mitigated, which is the honest way to put it: when an entry ships,
       the living spec it updates **is** in census and stays covered, but the roadmap note keeps
       whatever it said, unscanned, and **nothing mechanical corrects it**. Naming a workflow
       convention as the thing that holds the line would be the exact move the first paragraph of
       this module rejects — prose cannot be made to stay true; a failing test can.
    5d. **The floors are aggregates, and the anchor is kind-blind. What each one actually
       catches is worth stating exactly, because two earlier versions of this item credited the
       wrong mechanism.** There are two ways to take a census tree out of the walk, and they are
       not covered by the same thing. Removing it **by excluding it** is caught by
       `assert_no_dead_entry`, which requires every census entry to contribute a file to the scan
       **after** exclusions. Removing it **by deleting its entry** is invisible to that check —
       it iterates the entries that are *in* `SCOPE`, and a deleted one is not — so the only
       defence is the path-set anchor, which is in the suite, and which stops defending the
       moment `SCOPE` and the prose of rule 11 are edited in the same commit. Measured: dropping
       the `backend/alembic/versions` entry removes 17 files, exits **0**, and prints a census
       list of five trees where there were six. Removing a large part of a tree is caught by the
       floors:
       `sdd/specs` alone is 53 of the 94 walked Markdown files, so excluding it lands at 41,
       under the floor of 80. What is caught by **neither** is a subtree small enough to stay
       above both floors — excluding `backend/app/integrations` costs 45 files and passes, and
       `backend/app/audit` costs 11. That second one is worth naming rather than leaving to the
       class: it holds `AuditLogModel`, one of the two docstrings whose drift is this guard's
       stated motive. And `test_the_authority_names_exactly_the_paths_in_scope` does **not** close that:
       it compares a set of paths, kind-blind, so a path listed in the prose under the wrong
       heading — named as census while `SCOPE` excludes it — keeps the anchor green while telling
       a reader of rule 11 the opposite of the truth. That is by design (D11 anchors routes, not
       kinds or motives), and it means the anchor is a defence against a silent scope, not
       against a mislabelled one. It also lives in the suite and not in the binary, unlike the
       dead-entry checks.
    5c. **An attribution that names its column by reference instead of naming it** — "la única
       columna que este change hereda como primer escritor". This is the residual that dropping
       the meta-vocabulary from the sink axis opens: such a block used to be reported through
       `regla 11`, and now carries no sink term at all. The shape exists —
       `sdd/changes/archive/2026-08-08-access-notifications/design.md:169` is the measured
       example — but it lives in an out-of-census tree, so the cost **in scope today is zero
       blocks**. What was bought for it is the three false positives that had `main` red.
    7. **A census column named bare, without its table** — `payload` and `error` rather than
       `webhook_events.payload`. The sink axis matches the qualified column or the table name,
       so an unqualified mention of an ambiguous word like `payload` is invisible. This is the
       mirror of 3b, and it has a live example:
       `docs/adr/0007-webhook-event-retry-columns.md:43` attributes both columns and is missed
       on this axis, not on the ownership one. Qualifying the columns in the sink axis would
       not fix it; matching bare `payload`/`error` would fire on half the codebase.
    6. **Prose that is not a docstring or a `#` run**: a trailing inline comment
       (`changes = Column(JSON)  # audit_logs.changes, first writer is us`) never starts a line
       with `#`, and a string argument like SQLAlchemy's `Column(..., comment=...)` or
       Pydantic's `Field(description=...)` is not collected either — both are natural places to
       write who owns a column.
    8. **Ownership of a notification TYPE or enum member rather than a column**, and this change
       settles what that means rather than only naming it. R1.3 of `rule11-ownership-single-source`
       put enum-member attribution deliberately IN scope of *the rule*, and this guard cannot
       enforce that criterion: the sink axis is fed by column and table names, so a block naming
       only a notification type carries no sink term. **Measured on the pre-sweep tree**:
       `sdd/specs/cleaning.md` said "Este es el primer escritor de `CLEANING_TASK_ASSIGNED`",
       fired the ownership axis, and was invisible on the sink axis — the sweep removed it by
       hand, not because this guard asked.

       What is now decided, and is why `sdd/specs/access-notifications.md` was not edited:
       **attributing an enum member is not attributing a sink, for this guard.** The three
       blocks that had `main` in the red were exactly that shape, caught **by accident** through
       the word `censo` — a word about the mechanism, not about any column. Removing the
       meta-vocabulary does not narrow the rule; it aligns the guard's behaviour with what this
       residual always said about it. Adding the enum members to the sink axis remains the
       obvious fix and remains deliberately undone: there are far more of them than columns,
       they are renamed freely, and a sink axis that tracks them would be the unmaintainable
       list `rule11-ownership-single-source` existed to abolish.
    """
    assert not offending(
        "`audit_logs.changes` is a cleartext sink; this capability populates it from here."
    )
    # Residual 8, pinned: the enum-shaped copy is invisible, and stays measured rather than
    # asserted in prose alone. If a future sink axis learns notification types, this reddens and
    # the residual above has to come out.
    assert not offending("Este es el primer escritor de `CLEANING_TASK_ASSIGNED`.")
    # Residual 5c, pinned to the shape and not to the file, which lives out of census.
    assert not offending(
        "Es la aplicación de la regla 11 a la única columna que este change hereda como "
        "primer escritor."
    )


# ── `SCOPE`: the scope is a datum, and a dead entry is red ─────────────────────────────────


def test_every_scope_entry_has_a_written_reason() -> None:
    assert SCOPE
    for entry in SCOPE:
        assert entry.reason.strip(), (
            f"the scope entry `{entry.path}` ({entry.kind}) has no reason written. An exclusion "
            "or an exemption without a motive is one anyone can widen unnoticed"
        )


def test_every_scope_entry_resolves_to_a_path_the_scan_walks() -> None:
    """A stale entry is a standing hole nobody is told about.

    This is `test_every_declared_exception_still_earns_its_place` widened from the exemptions to
    the whole of `SCOPE` (R2.4). An exclusion whose tree was renamed silently stops excluding
    anything; a census root that was moved silently stops being scanned; both look identical to
    a green. Requiring every entry to name a path the scan actually reaches turns "no longer
    corresponds to anything" into a red test instead of silence.
    """
    walked = dict(module.prose_files(SCOPE, ROOT) + module.code_files(SCOPE, ROOT))
    census_roots = [
        entry.path
        for entry in SCOPE
        if entry.kind in (Kind.CENSUS_PROSE, Kind.CENSUS_CODE)
    ]

    for entry in SCOPE:
        target = ROOT / entry.path
        if entry.kind is Kind.AUTHORITY:
            assert target.is_file(), (
                f"the authority `{entry.path}` is not a file: the rule 11 table is the referent "
                "every other entry is measured against"
            )
            continue
        if entry.kind in (Kind.CENSUS_PROSE, Kind.CENSUS_CODE):
            assert any(
                relative.startswith(entry.path + "/") for relative in walked
            ), (
                f"the census tree `{entry.path}` contributes no file to the scan — the entry is "
                "dead, and everything the tree was meant to cover is unwatched"
            )
            continue
        if entry.kind is Kind.OUT_OF_CENSUS:
            assert target.exists(), (
                f"`{entry.path}` is excluded but no longer exists — the entry is dead and "
                "should be deleted, or the tree moved and the entry should follow it"
            )
            assert any(
                entry.path == root or entry.path.startswith(root + "/")
                for root in census_roots
            ), (
                f"`{entry.path}` is excluded but lies outside every census tree, so it excludes "
                "nothing: the entry is decorative and hides that the path is unscanned for a "
                "different reason"
            )
            continue
        assert entry.path in walked, (
            f"`{entry.path}` is exempted but the scan no longer walks it — the entry is dead "
            "and should be deleted, or the file moved and the entry should follow it"
        )


def test_every_declared_exception_still_earns_its_place() -> None:
    """`EXCEPTION` skips a whole FILE, so an entry that stops being necessary leaves that file
    permanently unwatched with nothing to say so.
    """
    walked = dict(module.prose_files(SCOPE, ROOT) + module.code_files(SCOPE, ROOT))
    exempted = module.exception_paths(SCOPE)
    assert exempted
    for relative in exempted:
        path = walked[relative]
        assert offending(path.read_text(encoding="utf-8"), python=path.suffix == ".py"), (
            f"{relative} is exempted but no longer contains anything the guard would report. "
            "Delete the entry: an exception that exempts nothing is a file silently outside "
            "the scan."
        )


# ── The silent failure: a scope that walks nothing must be red ─────────────────────────────


def test_an_empty_scope_is_red_and_not_zero_offenders() -> None:
    """R4.3, and the worst failure this guard has, because it is the silent one."""
    with pytest.raises(GuardError, match="empty"):
        module.check_tree_is_visible((), ROOT)
    with pytest.raises(GuardError):
        module.offenders((), ROOT)


def test_a_missing_prose_tree_is_red_and_not_zero_offenders(tmp_path: Path) -> None:
    """An incomplete checkout walks nothing; that must never be reported as "nothing there".

    The authority is what fails first, and deliberately: it is the referent every other entry is
    measured against, so a root without it is not a narrower scan but no scan at all.
    """
    with pytest.raises(GuardError, match="the authority"):
        module.check_tree_is_visible(SCOPE, tmp_path)

    # And a root that has the authority but not the rest of the prose fails on the tree itself.
    (tmp_path / "sdd" / "steering").mkdir(parents=True)
    (tmp_path / "sdd" / "steering" / "security.md").write_text(
        module.TABLE_HEADER, encoding="utf-8"
    )
    with pytest.raises(GuardError, match="incomplete checkout"):
        module.check_tree_is_visible(SCOPE, tmp_path)


def test_an_unparseable_python_file_is_red() -> None:
    with pytest.raises(GuardError, match="could not parse"):
        module._python_blocks("def broken(:\n", source="fake.py")


def test_a_scope_entry_without_a_reason_is_red() -> None:
    scope = (
        ScopeEntry("sdd/steering/security.md", Kind.AUTHORITY, ""),
        ScopeEntry("sdd", Kind.CENSUS_PROSE, "prose"),
    )
    with pytest.raises(GuardError, match="no reason written"):
        module.check_tree_is_visible(scope, ROOT)


def test_a_string_kind_is_coerced_and_an_unknown_one_is_red() -> None:
    """`Kind` is a `StrEnum`, which makes the near-miss look identical to the real thing.

    An entry built with the string `"census-prose"` instead of `Kind.CENSUS_PROSE` compares equal
    to the member but is not it, so an `is` comparison in the walk would skip that whole tree
    while every `==` validation accepted the entry. That is a census tree that validates and is
    never scanned — the silent green this guard exists to make impossible.
    """
    assert ScopeEntry("sdd", "census-prose", "a reason").kind is Kind.CENSUS_PROSE
    with pytest.raises(GuardError, match="unknown kind"):
        ScopeEntry("sdd", "not-a-kind", "a reason")


def test_a_dead_exclusion_is_red_in_the_guard_itself() -> None:
    """R2.4 binds the guard, not only this suite.

    `make check-rule11-ownership` is as much "the system" as `pytest scripts/` is, so an entry
    that corresponds to nothing has to redden the binary too.
    """
    with pytest.raises(GuardError, match="no longer exists"):
        module.check_tree_is_visible(
            SCOPE + (ScopeEntry("sdd/gone", Kind.OUT_OF_CENSUS, "a tree that is not there"),),
            ROOT,
        )
    with pytest.raises(GuardError, match="excludes\\s+nothing|excludes nothing"):
        module.check_tree_is_visible(
            SCOPE + (ScopeEntry("frontend", Kind.OUT_OF_CENSUS, "outside every census tree"),),
            ROOT,
        )


def test_a_dead_exception_is_red_in_the_guard_itself() -> None:
    """The most dangerous of the three kinds: it exempts a whole file."""
    with pytest.raises(GuardError, match="exempts nothing"):
        module.check_tree_is_visible(
            SCOPE
            + (ScopeEntry("scripts/gone.py", Kind.EXCEPTION, "a file that is not there"),),
            ROOT,
        )


def test_an_exclusion_that_swallows_a_census_tree_is_red() -> None:
    """N1: the dangerous direction, because every existence check passes.

    An `OUT_OF_CENSUS` entry naming a whole census tree removes it from the walk while the tree
    is still on disk, so the tree resolves, the exclusion resolves, and the green summary still
    NAMES it as census. Measured when this was open: excluding `backend/app` took the scan from
    801 Python files to 408 and reported zero offenders — half the code corpus, including the two
    model docstrings whose drift is the reason this guard exists.
    """
    with pytest.raises(GuardError, match="contributes no file to the scan"):
        module.check_tree_is_visible(
            SCOPE + (ScopeEntry("backend/app", Kind.OUT_OF_CENSUS, "swallow it whole"),),
            ROOT,
        )
    with pytest.raises(GuardError, match="contributes no file to the scan"):
        module.check_tree_is_visible(
            SCOPE + (ScopeEntry("scripts", Kind.OUT_OF_CENSUS, "swallow it whole"),),
            ROOT,
        )


def test_the_code_corpus_has_a_floor_of_its_own() -> None:
    """Until this was measured, only the Markdown half of the scan had an aggregate floor."""
    assert module.MINIMUM_PYTHON_FILES > 0
    assert len(module.code_files(SCOPE, ROOT)) >= module.MINIMUM_PYTHON_FILES


def test_a_census_code_tree_without_python_is_red() -> None:
    """A code tree contributing no `.py` is the same failure as a prose tree with no `.md`."""
    with pytest.raises(GuardError, match="holds no `.py` file"):
        module.check_tree_is_visible(
            SCOPE + (ScopeEntry("docs/diagrams", Kind.CENSUS_CODE, "no python lives here"),),
            ROOT,
        )


def test_an_unreadable_file_is_red_with_its_own_message(tmp_path: Path) -> None:
    """Reading is part of the chain, so it fails like the rest of it (R1.4).

    A non-UTF-8 byte in a scanned file used to escape `main()` as a bare traceback that never
    named the file the guard could not look at. The guard stayed red, so the security property
    held, but "with its own message" is what R1.4 actually asks for.
    """
    bad = tmp_path / "latin1.md"
    bad.write_bytes("`audit_logs` y su primer escritor est\xe1 aqu\xed.\n".encode("latin-1"))
    with pytest.raises(GuardError, match="could not read"):
        module.read(bad, "latin1.md")

    with pytest.raises(GuardError, match="could not read"):
        module.read(tmp_path / "does-not-exist.md", "does-not-exist.md")


def test_a_census_tree_that_does_not_resolve_is_red() -> None:
    scope = SCOPE + (
        ScopeEntry("backend/nonexistent", Kind.CENSUS_CODE, "a tree that is not there"),
    )
    with pytest.raises(GuardError, match="does not exist"):
        module.check_tree_is_visible(scope, ROOT)


# ── The authority's prose is anchored to `SCOPE` ───────────────────────────────────────────

AUTHORITY_FILE = "sdd/steering/security.md"
SECTION_HEADING = "## Sumideros de texto en claro (regla 11)"
SCOPE_MARKER = "<!-- rule11-scope -->"


def scope_sentence() -> str:
    """The one paragraph of the rule 11 section that enumerates the guard's scope.

    Located by the section's literal heading and then by a stable marker, and **never** by
    position. If either is missing the test fails naming what it could not find: passing in the
    void is the same failure as a guard that walks zero files.
    """
    text = (ROOT / AUTHORITY_FILE).read_text(encoding="utf-8")
    assert SECTION_HEADING in text, (
        f"`{AUTHORITY_FILE}` no longer contains the heading {SECTION_HEADING!r}. The rule 11 "
        "section moved or was renamed; this anchor cannot verify what it cannot find"
    )
    section = text.split(SECTION_HEADING, 1)[1].split("\n## ", 1)[0]
    assert SCOPE_MARKER in section, (
        f"the rule 11 section of `{AUTHORITY_FILE}` no longer carries the marker "
        f"{SCOPE_MARKER!r}, which is what pins its scope sentence to `SCOPE`. Restore the "
        "marker on the line above that sentence, or this anchor is silently verifying nothing"
    )
    after = section.split(SCOPE_MARKER, 1)[1].lstrip("\n")
    paragraph = after.split("\n\n", 1)[0]
    assert paragraph.strip(), f"the paragraph after {SCOPE_MARKER!r} is empty"
    return paragraph


def test_the_authority_names_exactly_the_paths_in_scope() -> None:
    """D11: the prose of the rule and the scope of the guard cannot drift apart in silence.

    Both directions, and **paths only** — not counts, not motives. R5 asks that the authority
    not age in the same movement that fixes it, and the counts of this very section already aged
    four times without anything turning red. Verifying that the `reason` of an entry matches
    what the prose says about it would be semantic analysis; verifying that the two name the
    same paths is arithmetic, and it is the half that rots.
    """
    named = {
        token.rstrip("/")
        for token in re.findall(r"`([^`]+)`", scope_sentence())
        if "/" in token
    }
    declared = {entry.path for entry in SCOPE}

    assert named == declared, (
        "the scope sentence of the rule 11 section and `SCOPE` do not name the same paths.\n"
        f"  only in the prose: {sorted(named - declared)}\n"
        f"  only in `SCOPE`:   {sorted(declared - named)}\n"
        "`SCOPE` is the source; the sentence is what a reader of the rule is entitled to "
        "believe. Whichever is wrong, they cannot disagree."
    )
