"""The ownership of a rule 11 sink is declared in one table, and nowhere else.

Rule 11 of `sdd/steering/security.md` says of itself that its *contract* lives in one place,
and that is true. What did not live in one place is the **ownership**: who writes each sink
today and who will inherit it was restated across the tree — in specs, roadmap notes, model
docstrings, a migration and the test suite — and three of those copies had drifted
into saying something false — `AuditLogModel` claimed "Nothing writes here yet" with twelve
callers, `NotificationLogModel` claimed `last_error` had no writer months after it got one, and
`domain-foundation-financial.md` claimed "una única excepción" when there were four.

**Prose cannot be made to stay true; a failing test can.** The count of copies went 4 → 5 → 6 in
successive review rounds of one change, fixing one and finding the next, and copy number eight
was written by someone who had this very roadmap entry in front of them — citing the authority
and restating the ownership in the same sentence. That is the evidence that pointing at the
table does not prevent the copy. Only a red test does.

What this file asserts: no block outside the table declares who writes, or who will inherit, a
column of the rule 11 census.
"""

import ast
import re
from pathlib import Path

# --- where the prose lives ------------------------------------------------------------
#
# `docker-compose.yml` mounts only `./backend` into the container, so `sdd/` and `docs/` are
# invisible here unless something puts them there. Same asymmetry, and the same remedy, as
# `tests/provenance/test_workflow_to_endpoint_wiring.py`: a read-only bind mount under
# `/workspace/`, and the repository layout as the last resort so a complete checkout (CI, or a
# developer running outside Docker) works with no mount at all. Two candidates and no
# environment override, deliberately: the sibling test has one, but an env var here would be a
# one-line way to aim this scan at an empty directory and defeat the sentinel below.

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def _prose_roots() -> list[Path]:
    candidates = [
        (Path("/workspace/sdd"), Path("/workspace/docs")),
        (REPO_ROOT / "sdd", REPO_ROOT / "docs"),
    ]
    for sdd, docs in candidates:
        if (sdd / "steering" / "security.md").is_file():
            return [path for path in (sdd, docs) if path.is_dir()]
    return []


#: The authority. Ownership belongs here, so it is the one file the scan must not reclaim.
AUTHORITY = Path("steering/security.md")

#: Proof the scan is looking at the real tree. A bind mount whose source is missing is created
#: by Docker as an EMPTY DIRECTORY, so without this the guard would walk zero files and pass.
TABLE_HEADER = "| Columna | Forma | Quién la escribe"

#: Below this, something is wrong with the mount rather than with the tree.
MINIMUM_MARKDOWN_FILES = 40


# --- the two axes ---------------------------------------------------------------------
#
# A block is reported only when it carries BOTH. One axis alone is useless: "primer escritor"
# appears all over the tree about things that are not rule 11 sinks — `conversations`,
# `owner_approvals` the table, `reservations.guest_id`, `current_operational_state`,
# `wifi_password_encrypted` — so a single-axis scan would report twenty sites and need an
# exception list naming every one of them, which is what `test_free_text_sink_contract.py`
# documents as proof of nothing.

#: The columns of the census, the tables that hold them, and the vocabulary that refers to the
#: rule itself. No count here: the table governs how many there are, and this tuple went stale
#: once already when `revenue-pricing` merged two columns in mid-review.
#:
#: **The bare table names are here because leaving them out was measured, not guessed.** Run
#: against the pre-sweep tree, a column-only axis caught ten of the thirteen swept files and
#: missed three — `user-management.md` said "primer escritor real de `audit_logs`",
#: `domain-foundation-financial.md` said "las tres de `webhook_events` ya tienen escritor vivo",
#: and `WebhookEventModel` said "`reservations-webhooks` is the writer". All three name the
#: TABLE and attribute it. A table name alone is common enough to be useless as a single axis,
#: but it is safe here because a block is only reported when the ownership axis fires too.
#:
#: **`incidents` and `messages` are deliberately NOT here as bare table names**, and the
#: asymmetry is a judgement rather than an oversight: they are ordinary English words that
#: appear all over this codebase's prose, so as an axis they would fire on blocks that have
#: nothing to do with the census. The cost is stated in the residual below — an attribution
#: that names one of those two tables without naming a column goes unreported. The other four
#: are unambiguous identifiers and carry no such cost.
SINK_TERMS = (
    "audit_logs",
    "webhook_events",
    "notification_logs",
    "owner_approvals",
    # `revenue-pricing` merged two columns into the census while this change was in review.
    # They are here because the sink axis is fed by the table, so a column the table governs and
    # this tuple does not is a blind spot the green would hide — residual 3, arriving for real
    # rather than as a warning. `price_recommendations` and `pricing_rules` are unambiguous
    # identifiers, so they go in as bare table names like the four above.
    "price_recommendations",
    "pricing_rules",
    "incidents.title",
    "incidents.description",
    "incidents.ai_summary",
    "incidents.ai_classification",
    # `tech-incident-context` (2026-08-21) added two columns to the census, and they go in here
    # for the reason residual 3 below states: the sink axis is fed by this tuple, so a column the
    # table governs and this does not is a blind spot the green would hide. That is the same
    # blindness `webhook_events.event_type` had for two changes.
    #
    # `properties.access_notes` goes in **qualified**, not as the bare table name `properties`:
    # the asymmetry documented above for `incidents` and `messages` applies to it too — the word
    # appears all over this codebase's prose — and the other two notes of that table are not
    # census columns, so a bare `properties` would fire on blocks about them.
    "incidents.assignment_note",
    "properties.access_notes",
    "messages.content",
    "messages.intent",
    "messages.metadata",
    "regla 11",
    "rule 11",
    "sumidero de texto en claro",
    "cleartext sink",
    "censo",
)

#: Saying who writes it, or who will. Same provenance as the sink axis: `is the writer` and
#: `ya tiene(n) escritor` are here because the pre-sweep tree used them and an earlier version
#: of this tuple walked past them.
OWNERSHIP_PATTERNS = (
    r"primer(?:os)? escritor(?:es)?",
    r"escritor(?:es)? vivo",
    r"(?:ya\s+)?tienen?\s+escritor",
    r"es\s+el\s+escritor",
    r"is\s+the\s+writer",
    r"first writer",
    r"writes here",
    r"sin escritor",
    r"nothing writes here yet",
    r"hereda(?:rá)?\s+(?:ese|su|el)\s+contrato",
    r"inherits?\s+(?:that|the|its)\s+contract",
    r"quién\s+la\s+escribe",
    r"quien\s+la\s+escribe",
)
_OWNERSHIP = re.compile("|".join(OWNERSHIP_PATTERNS), re.IGNORECASE)


# --- what is deliberately not walked ----------------------------------------------------
#
# Every entry carries its reason in the entry, the way `test_free_text_sink_contract.py` does:
# an exclusion without a written motive is an `assert` anyone can widen unnoticed.

EXCLUDED_DIRECTORIES = {
    # A change record is the SAME document before and after `/sdd:archive` moves it. Excluding
    # only `archive/` would let the guard go from red to green on a `mv`, without a word
    # changing. So the whole tree goes, not just the destination (design D3, amends R3.3).
    "sdd/changes",
    # ADRs are immutable by convention — superseded, never edited — which is the same argument
    # R3.3 makes for archived records. Immutability is the whole motive: measured, the detector
    # reports ZERO blocks across `docs/adr/` today, so this exclusion is currently costing
    # nothing. (An earlier version of this comment claimed ADR 0007 was its one live case. That
    # was wrong, and instructively so: ADR 0007:43 DOES attribute — "declarando además a ese
    # change como **escritor vivo** de `payload` y `error`" fires the ownership axis — and what
    # misses is the SINK axis, because it names two census columns bare, without their table.
    # That is residual 7 below, and ADR 0007:43 is its measured example.)
    "docs/adr",
}

#: Files that legitimately carry both axes. Each entry states WHY, and the list starts with one.
DECLARED_EXCEPTIONS = {
    # This change's own roadmap note. It states the pathology — "la propiedad … está reafirmada
    # en seis artefactos", "y su primer escritor será X" — in order to refute it and to record
    # the criterion that was asked for. R2.4 keeps what enunciates the false belief to deny it,
    # and this is the only place the request itself is on record.
    "sdd/roadmap/rule11-ownership-single-source.md": (
        "states the pathology in order to refute it; the only record of why this guard exists"
    ),
    # This file. Its two axes ARE the vocabulary, so every phrase it hunts appears in it by
    # construction — including in the meta-tests that prove the scan works. Exempting the
    # detector from itself is not a hole: there is no column here whose ownership a reader
    # could take away, and the alternative is a guard that cannot describe what it does.
    "backend/tests/test_rule11_ownership.py": (
        "the detector's own vocabulary and meta-tests; not an attribution of any column"
    ),
}


def _is_excluded(relative: str) -> bool:
    return any(relative == path or relative.startswith(path + "/") for path in EXCLUDED_DIRECTORIES)


# --- blocks ------------------------------------------------------------------------------


def _markdown_blocks(text: str) -> list[tuple[int, str]]:
    """Paragraphs and bullets, a bullet's continuation lines belonging to it.

    The block and not the line is the decision that makes this guard work at all: copy number
    eight split the citation and the attribution across `messaging-ai.md:93` and `:94`, so a
    line-by-line scan would have walked straight past the case that motivated the change.
    """
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    start = 1
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        starts_bullet = bool(re.match(r"^([-*+]|\d+\.)\s", stripped))
        if not stripped:
            if current:
                blocks.append((start, "\n".join(current)))
                current = []
            continue
        if starts_bullet and current:
            blocks.append((start, "\n".join(current)))
            current = []
        if not current:
            start = number
        current.append(line)
    if current:
        blocks.append((start, "\n".join(current)))
    return blocks


def _python_blocks(text: str) -> list[tuple[int, str]]:
    """Docstrings, plus runs of contiguous `#` comments.

    Only prose: a block of code that happens to mention a column name is not a declaration of
    ownership, and reporting it would be the false-positive flood the two axes exist to avoid.
    """
    blocks: list[tuple[int, str]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        # Fail closed, for the same reason the mount has a sentinel: "we could not look" must
        # never be reported as "there was nothing there".
        raise AssertionError(f"the guard could not parse a file it is meant to scan: {error}") from error

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            continue
        body = node.body[0]
        blocks.append((getattr(body, "lineno", 1), doc))

    run: list[str] = []
    start = 1
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            if not run:
                start = number
            # `#:` is Sphinx, and `lstrip("#")` leaves its colon behind. Every continuation
            # line of a `#:` run therefore began with `": "`, so a phrase spanning two lines
            # read as `"…this module is\n: the writer of …"` — and `\s+` does not match a
            # colon. The guard's own hunted string, present verbatim in
            # `app/maintenance/domain/entities.py`, was reported as absent for that reason
            # alone. Found by the security panel of `cleaner-incident-report` section 2; it is
            # not the paraphrase residual that `test_what_this_guard_does_not_catch` records,
            # it is the exact vocabulary going unseen. Stripping the colon newly reports
            # exactly one block across `app/`, `tests/` and `alembic/versions/` — measured
            # before the change, not hoped for afterwards.
            run.append(stripped.lstrip("#").lstrip(":").strip())
            continue
        if run:
            blocks.append((start, "\n".join(run)))
            run = []
    if run:
        blocks.append((start, "\n".join(run)))
    return blocks


def _offending_blocks(text: str, *, python: bool) -> list[tuple[int, str, str]]:
    blocks = _python_blocks(text) if python else _markdown_blocks(text)
    offenders = []
    for line, block in blocks:
        lowered = block.lower()
        if not any(term.lower() in lowered for term in SINK_TERMS):
            continue
        match = _OWNERSHIP.search(block)
        if match:
            offenders.append((line, match.group(0), " ".join(block.split())[:200]))
    return offenders


# --- the scan ----------------------------------------------------------------------------


def _prose_files() -> list[tuple[str, Path]]:
    found = []
    for root in _prose_roots():
        prefix = root.name
        for path in sorted(root.glob("**/*.md")):
            relative = f"{prefix}/{path.relative_to(root).as_posix()}"
            if relative == f"sdd/{AUTHORITY.as_posix()}" or _is_excluded(relative):
                continue
            found.append((relative, path))
    return found


def _code_files() -> list[tuple[str, Path]]:
    found = []
    for sub in ("app", "alembic/versions", "tests"):
        root = BACKEND_ROOT / sub
        for path in sorted(root.glob("**/*.py")):
            found.append((f"backend/{sub}/{path.relative_to(root).as_posix()}", path))
    return found


def test_the_prose_tree_is_actually_visible() -> None:
    """Fail-closed, and never `skip`.

    A bind mount whose source is missing is created by Docker as an empty directory, so a guard
    without this sentinel would walk zero files and report success. `skip` would be almost as
    bad: in `-rs` output it reads as "did not apply", which is exactly the wrong thing for a
    security control to say when its input has vanished.
    """
    roots = _prose_roots()
    assert roots, (
        "the prose tree is not reachable. Inside Docker it arrives through the read-only "
        "bind mounts of `docker-compose.yml` (`./sdd:/workspace/sdd:ro`); a container started "
        "before those lines existed will not have them, so `make down && make up`."
    )

    authority = roots[0] / AUTHORITY
    assert authority.is_file(), f"{authority} is missing: the rule 11 table is the referent"
    assert TABLE_HEADER in authority.read_text(encoding="utf-8"), (
        f"{authority} does not contain the rule 11 table header. Either the table moved or "
        "the mount is pointing somewhere unexpected; the guard is not measuring what it claims."
    )
    scanned = len(_prose_files())
    assert scanned >= MINIMUM_MARKDOWN_FILES, (
        f"only {scanned} Markdown files are visible, below the {MINIMUM_MARKDOWN_FILES} this "
        "tree should have. A partially-populated mount looks exactly like this — the scan is "
        "walking something, just not everything. `make down && make up`."
    )
    docs_root = next((root for root in _prose_roots() if root.name == "docs"), None)
    assert docs_root is not None and any(docs_root.glob("*.md")), (
        "the `docs/` half of the prose tree is empty or missing. It is validated separately "
        "because `_prose_roots()` anchors on `sdd/steering/security.md`: with only that check, "
        "an empty or mistyped `./docs` mount would be admitted by a bare `is_dir()` and its "
        "whole subtree would go unscanned while the suite stayed green."
    )


def test_no_block_outside_the_table_declares_who_writes_a_sink() -> None:
    reported: list[str] = []
    for relative, path in _prose_files() + _code_files():
        if relative in DECLARED_EXCEPTIONS:
            continue
        offenders = _offending_blocks(
            path.read_text(encoding="utf-8"), python=path.suffix == ".py"
        )
        for line, phrase, excerpt in offenders:
            reported.append(f"  {relative}:{line} — {phrase!r}\n      {excerpt}")

    assert not reported, (
        "these blocks name a rule 11 sink AND say who writes it:\n"
        + "\n".join(reported)
        + "\n\nOwnership of a sink is declared in the rule 11 table of "
        "`sdd/steering/security.md`, and nowhere else — that is what rule 11 means by living "
        "in one place. Keep here what is local (that the column is a cleartext sink, that its "
        "contract is rule 11, why it is dangerous in THIS module, and the mechanism that "
        "enforces it if it lives here); move who writes it, or who will inherit it, to the "
        "table. If this block is a legitimate exception, add it to DECLARED_EXCEPTIONS with "
        "its reason written out."
    )


def test_the_scan_catches_what_it_claims_to() -> None:
    """The enforcement mechanism gets its own test, like its two neighbours'."""
    both_axes = "`audit_logs.changes` is one of them, and this change is its first writer."
    assert _offending_blocks(both_axes, python=False)

    # Split across two lines of one bullet — copy number eight's exact shape.
    split = "- declara `messages.content` en el censo de la regla 11,\n  con esta capability como primer escritor vivo."
    assert _offending_blocks(split, python=False)

    # One axis only: neither is reportable.
    assert not _offending_blocks("`conversations` has its first writer here.", python=False)
    assert not _offending_blocks("`audit_logs.changes` is a cleartext sink; see rule 11.", python=False)

    # Two different paragraphs are two blocks, which is the documented residual below.
    assert not _offending_blocks(
        "`audit_logs.changes` is a cleartext sink.\n\nThis change is its first writer.",
        python=False,
    )

    # Python docstrings and comment runs, not code.
    assert _offending_blocks('"""`messages.intent` — rule 11. First writer: us."""', python=True)
    assert _offending_blocks(
        "# `notification_logs.body` is a rule 11 sink\n# and access-notifications is its first writer",
        python=True,
    )


def test_what_this_guard_does_not_catch() -> None:
    """R3.4: say what the green does not cover, so it is not read as completeness.

    Every item is a shape that exists in the tree today or that defeated an earlier version of
    a sibling guard — not a list of good intentions.

    1. **Paraphrase.** An attribution with none of the ownership vocabulary ("esta capability
       estrena la columna", "desde aquí se rellena") is invisible. The axis is a vocabulary,
       not a semantic analyser. The section 2 panel of this very change found a paraphrased
       copy that a literal grep could not see, so this is measured, not hypothetical.
    2. **Split across two blocks** — the column in one paragraph, the owner in the next. The
       block closes the two-contiguous-lines case, not the two-paragraph one.
    3. **A column not yet in the census.** The sink axis is fed by the table, so column number
       seventeen is invisible until it is declared there. That is the same blindness
       `webhook_events.event_type` had for two changes.
    3b. **`incidents` or `messages` named as a bare table**, without one of their columns. The
       other four census tables are matched by name; those two are common English words and
       would fire on unrelated prose, so they are matched only at column level. A real case of
       this shape exists today and is deliberately left unreported:
       `app/audit/domain/actions.py` says the guest portal "was the first writer of
       `incidents`" — which is about rule 9's audit actions, not about who owns a rule 11 sink.
    4. **The `app/cli/seed_demo.py` hole** in the `maintenance` free-text guard
       (`security.md`): out of scope by the proposal's decision, and named here rather than
       left for the green to imply.
    5. **The excluded trees** of `EXCLUDED_DIRECTORIES` and anything in `DECLARED_EXCEPTIONS`,
       and the magnitude is worth stating rather than implying: `sdd/changes/` holds **36
       blocks that fire both axes** today, about sixteen of them already frozen under
       `archive/` — including `2026-08-01-user-management/proposal.md`, which still carries
       verbatim the "primer escritor real de `audit_logs`" sentence the sweep removed from
       `sdd/specs/user-management.md`. The exclusion is right (D3: a change record is the same
       document before and after the `mv`), but it means the largest prose corpus in the
       repository is exempt from the thesis that prose cannot be made to stay true. That is a
       measured concession, not a formality.
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
    8. **Ownership of a notification TYPE or enum member rather than a column** — and this is
       the one that reaches a criterion of this change rather than merely a shape. R1.3 puts
       enum-member attribution deliberately IN scope ("el criterio es qué hecho se duplica, no
       de qué tipo es el objeto que lo lleva"), because attributing `GUEST_ESCALATION` restates
       what the `notification_logs.subject`/`body` row already owns. This guard cannot enforce
       that criterion: the sink axis is fed by column and table names, so a block naming only a
       notification type carries no sink term. **Measured on the pre-sweep tree**:
       `sdd/specs/cleaning.md` said "Este es el primer escritor de `CLEANING_TASK_ASSIGNED`",
       fired the ownership axis, and was invisible on the sink axis — the sweep removed it by
       hand, not because this guard asked. So of the thirteen sites the sweep covered, this
       detector reclaims twelve; the enum-shaped one is the exception, and R1.3's class of copy
       is the standing hole. Adding the enum members to the sink axis is the obvious fix and is
       left undone deliberately: there are far more of them than columns, they are renamed
       freely, and a sink axis that tracks them would be the unmaintainable list this change
       exists to abolish.
    """
    assert not _offending_blocks(
        "`audit_logs.changes` is a cleartext sink; this capability populates it from here.",
        python=False,
    )
    # Residual 8, pinned: the enum-shaped copy is invisible, and stays measured rather than
    # asserted in prose alone. If a future sink axis learns notification types, this reddens and
    # the residual above has to come out.
    assert not _offending_blocks(
        "Este es el primer escritor de `CLEANING_TASK_ASSIGNED`.",
        python=False,
    )
    assert DECLARED_EXCEPTIONS and all(reason for reason in DECLARED_EXCEPTIONS.values())
    assert "sdd/changes" in EXCLUDED_DIRECTORIES and "docs/adr" in EXCLUDED_DIRECTORIES


def test_every_declared_exception_still_earns_its_place() -> None:
    """A stale exemption is a standing hole nobody is told about.

    `DECLARED_EXCEPTIONS` skips a whole FILE, so an entry that stops being necessary — the
    roadmap note gets rewritten, the guard's own vocabulary moves — leaves that file
    permanently unwatched with nothing to say so. Requiring each entry to still produce an
    offending block turns "no longer needed" into a red test instead of silence.
    """
    by_path = dict(_prose_files() + _code_files())
    for relative in DECLARED_EXCEPTIONS:
        path = by_path.get(relative)
        assert path is not None, (
            f"{relative} is exempted but the scan no longer walks it — the entry is dead and "
            "should be deleted, or the file moved and the entry should follow it."
        )
        assert _offending_blocks(path.read_text(encoding="utf-8"), python=path.suffix == ".py"), (
            f"{relative} is exempted but no longer contains anything the guard would report. "
            "Delete the entry: an exception that exempts nothing is a file silently outside "
            "the scan."
        )
