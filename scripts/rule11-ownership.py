#!/usr/bin/env python3
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

**Why it is a script and not a test** (change `rule11-guard-trigger-and-scope`, D1): living in
`backend/tests/` made the guard depend on two things it does not need. Its **trigger** —
`backend-tests.yml` decides the area with `case "$f" in backend/* | …)`, so a prose-only commit,
which is the shape of every `/sdd:archive` commit, skipped the very suite that holds this guard.
And its **reach** — `sdd/` and `docs/` arrived through two read-only bind mounts that existed for
this file alone. Both are gone: the scan runs on the host's `python3` over a plain checkout,
from `make check-rule11-ownership` and from `.github/workflows/rule11-ownership.yml`, which has
no `paths:` filter and no area gate.

The declared cost of that move, stated here because the green must not imply it away: the
backend's `pytest` no longer runs this guard, so an offending docstring under `backend/app/**`
is now seen in CI and in `make check-rule11-ownership`, not in the local backend suite.

Contract: no arguments, run from anywhere. **Exit 0** when no block offends, naming and counting
what was scanned so the green reads as "it looked at this" and not as "it looked at nothing".
**Non-zero** in every other case, including any break in the chain — a guard whose input has
vanished must never report "no offenders".
"""

import ast
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: One origin, not two. The `/workspace/` candidate existed only because the scan ran inside the
#: backend container through a bind mount; with the guard on the host there is a single tree, and
#: a second candidate would be a second way to aim the scan at something that is not the repo.
REPO_ROOT = Path(__file__).resolve().parents[1]


class GuardError(Exception):
    """The chain broke, or the input is not the shape expected: red, never green."""


def read(path: Path, relative: str) -> str:
    """Read a file of the scan, or abort naming the one that could not be read.

    Reading is part of the chain, so it fails the way the rest of the chain fails (R1.4): a
    non-UTF-8 byte, a permission, a file that vanished between the walk and the read would
    otherwise leave `main()` as an uncaught traceback that never says which file the guard could
    not look at.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise GuardError(
            f"the guard could not read a file it is meant to scan: {relative}: {exc}"
        ) from exc


# --- the scope, as data -------------------------------------------------------------------
#
# What this guard walks, what it deliberately does not, and why — in ONE structure. Before
# `rule11-guard-trigger-and-scope` the answer was spread across `_prose_roots()`,
# `_code_files()`, `EXCLUDED_DIRECTORIES`, `DECLARED_EXCEPTIONS` and `AUTHORITY`, which is a
# scope nobody can audit in one reading. That mattered here more than anywhere: the defect this
# change fixes is that the guard's scope and its trigger were disjoint sets, and no structure
# said so.


class Kind(StrEnum):
    AUTHORITY = "authority"
    """The table itself: the one home of ownership, so the one file the scan must not reclaim."""

    CENSUS_PROSE = "census-prose"
    """A tree of prose that cites the authority. Every `.md` under it is walked."""

    CENSUS_CODE = "census-code"
    """A tree of code whose docstrings and `#` runs cite it. Every `.py` under it is walked."""

    OUT_OF_CENSUS = "out-of-census"
    """Prose that may cite the rule without restating it. Inside a census tree, not walked."""

    EXCEPTION = "exception"
    """One file that legitimately carries both axes, with its motive written in the entry."""


@dataclass(frozen=True)
class ScopeEntry:
    """A path, what it is to this guard, and why. `reason` is required and never empty."""

    path: str
    kind: Kind
    reason: str

    def __post_init__(self) -> None:
        """Coerce `kind` to a real `Kind`, because `StrEnum` makes the near-miss invisible.

        `Kind` is a `StrEnum`, so `ScopeEntry("sdd", "census-prose", …)` — the string rather than
        the member — compares equal to `Kind.CENSUS_PROSE` but is not it. Every `is` comparison
        would walk straight past that entry while every `==` validation accepted it, and the
        result is the silent failure this guard exists to make impossible: a census tree that
        validates and is never scanned. Coercing here means a kind that is not a `Kind` is red at
        import, and the comparisons below are all `==`.
        """
        # A trailing slash is the natural way to write a directory and it excluded NOTHING:
        # `_is_excluded` compares against `path` and `path + "/"`, so `backend/app/` matched
        # neither, while the decorative-exclusion check saw a path inside a census tree and
        # passed it. The hygiene check failed open. Normalising here is the fix, and it is the
        # right place because it makes every later comparison work on one form.
        normalised = self.path.rstrip("/")
        if not normalised:
            raise GuardError("a scope entry has an empty path, so it names nothing")
        object.__setattr__(self, "path", normalised)
        try:
            object.__setattr__(self, "kind", Kind(self.kind))
        except ValueError as exc:
            raise GuardError(
                f"the scope entry `{self.path}` declares an unknown kind {self.kind!r}. The "
                f"kinds are {', '.join(k.value for k in Kind)}"
            ) from exc


SCOPE: tuple[ScopeEntry, ...] = (
    ScopeEntry(
        "sdd/steering/security.md",
        Kind.AUTHORITY,
        "the rule 11 table: ownership belongs here, so it is the one file the scan must not "
        "reclaim",
    ),
    ScopeEntry(
        "sdd",
        Kind.CENSUS_PROSE,
        "specs, steering and change documents cite the census; this is where copy number eight "
        "was written by someone citing the authority in the same sentence",
    ),
    ScopeEntry(
        "docs",
        Kind.CENSUS_PROSE,
        "the PRD, the capability docs and the ADRs describe the same columns and are the other "
        "half of this project's prose",
    ),
    ScopeEntry(
        "backend/app",
        Kind.CENSUS_CODE,
        "model and adapter docstrings are where three of the drifted copies lived — "
        "`AuditLogModel` and `NotificationLogModel` among them",
    ),
    ScopeEntry(
        "backend/alembic/versions",
        Kind.CENSUS_CODE,
        "a migration's docstring describes the column it creates, which is the natural place to "
        "say who will write it",
    ),
    ScopeEntry(
        "backend/tests",
        Kind.CENSUS_CODE,
        "the suite states contracts about the columns it exercises, and the sweep found a copy "
        "here too",
    ),
    ScopeEntry(
        "scripts",
        Kind.CENSUS_CODE,
        "this guard now lives here, so the tree that holds it is walked like any other: "
        "otherwise the exception below would exempt a file nothing scans, which is the dead "
        "entry `test_every_declared_exception_still_earns_its_place` exists to forbid",
    ),
    ScopeEntry(
        "sdd/changes",
        Kind.OUT_OF_CENSUS,
        "A change record is the SAME document before and after `/sdd:archive` moves it. "
        "Excluding only `archive/` would let the guard go from red to green on a `mv`, without "
        "a word changing. So the whole tree goes, not just the destination (design D3, amends "
        "R3.3).",
    ),
    ScopeEntry(
        "docs/adr",
        Kind.OUT_OF_CENSUS,
        "ADRs are immutable by convention — superseded, never edited — which is the same "
        "argument R3.3 makes for archived records. Immutability is the whole motive: measured, "
        "the detector reports ZERO blocks across `docs/adr/` today, so this exclusion is "
        "currently costing nothing. (An earlier version of this comment claimed ADR 0007 was "
        "its one live case. That was wrong, and instructively so: ADR 0007:43 DOES attribute — "
        '"declarando además a ese change como **escritor vivo** de `payload` y `error`" fires '
        "the ownership axis — and what misses is the SINK axis, because it names two census "
        "columns bare, without their table. That is residual 7 below, and ADR 0007:43 is its "
        "measured example.)",
    ),
    ScopeEntry(
        "sdd/roadmap.md",
        Kind.OUT_OF_CENSUS,
        "a roadmap entry DECLARES WORK NOT DONE, so saying that a column has no writer yet is "
        "its function and not a restatement of the census. Without this, a roadmap entry forces "
        "an edit to a shared file in order to unblock somebody else's merge gate — which is "
        "what the review panel of `guest-portal-messaging` raised four times as a violation of "
        "the toolkit's rule 1. Measured cost of the exclusion, today: see "
        "`test_what_this_guard_does_not_catch`",
    ),
    ScopeEntry(
        "sdd/roadmap",
        Kind.OUT_OF_CENSUS,
        "the per-entry roadmap notes are the same kind of document as `sdd/roadmap.md` and are "
        "excluded for the same reason: they describe work that has no writer yet. This replaces "
        "the named exception for `sdd/roadmap/rule11-ownership-single-source.md`, which the "
        "exclusion now covers",
    ),
    ScopeEntry(
        "scripts/rule11-ownership.py",
        Kind.EXCEPTION,
        "the detector's own vocabulary; not an attribution of any column",
    ),
    ScopeEntry(
        "scripts/test_rule11_ownership.py",
        Kind.EXCEPTION,
        "the detector's meta-tests, which must contain every phrase it hunts in order to prove "
        "the scan works; not an attribution of any column",
    ),
)

#: Proof the scan is looking at the real tree, kept from the container era for a different
#: reason: a truncated checkout looks exactly like a partially-populated mount did.
TABLE_HEADER = "| Columna | Forma | Quién la escribe"

#: Below this, something is wrong with the checkout rather than with the tree. **Measured, with
#: deliberate headroom**: the scan walks 95 Markdown files on 2026-09-01 — it was 94 when this
#: floor was set on 2026-08-31, and the one that arrived since is this change's own
#: `sdd/specs/rule11-ownership-guard.md`, written in a later section than this line. The floor was
#: raised from 40 — a figure inherited from a tree of 180 that had become loose enough to admit
#: losing more than half the corpus — to 80. It is a floor and not a census: it catches a
#: truncated checkout, not a scope that quietly stops covering one tree. What catches THAT is the
#: anchor test, which makes every entry of `SCOPE` nameable in the rule's own prose.
MINIMUM_MARKDOWN_FILES = 80

#: The same floor for the code corpus, and it was missing: there was no Python equivalent at all,
#: so the half of the scan that lives under `backend/` and `scripts/` had no aggregate check
#: whatsoever. Measured 801 walked `.py` files on 2026-08-31, with the same deliberate headroom —
#: and note that task 4.1 removes one of them, which is inside it.
MINIMUM_PYTHON_FILES = 700


# --- the two axes ---------------------------------------------------------------------
#
# A block is reported only when it carries BOTH. One axis alone is useless: "primer escritor"
# appears all over the tree about things that are not rule 11 sinks — `conversations`,
# `owner_approvals` the table, `reservations.guest_id`, `current_operational_state`,
# `wifi_password_encrypted` — so a single-axis scan would report twenty sites and need an
# exception list naming every one of them, which is what `test_free_text_sink_contract.py`
# documents as proof of nothing.

#: The columns of the census and the tables that hold them. No count here: the table governs how
#: many there are, and this tuple went stale once already when `revenue-pricing` merged two
#: columns in mid-review.
#:
#: **The meta-vocabulary that used to be here came out, and the reason is a measurement.** Five
#: terms named the mechanism rather than anything the table governs — `regla 11`, `rule 11`,
#: `censo`, `sumidero de texto en claro`, `cleartext sink` — and they entered without ever being
#: measured. Recounted over the whole corpus on 2026-08-31, excluded trees included so the sample
#: was not the recut one: **50 blocks fire both axes through a column or a table of the census**,
#: and about twenty more matched the sink axis through meta-vocabulary alone.
#:
#: **The load-bearing figure is the in-scope one, and it is four** — recounted against the tree
#: this change ships, not against the one it started from. Every meta-only match but four lies in
#: an out-of-census tree or in one of the detector files. Three are
#: `sdd/specs/access-notifications.md:373`, `:526` and `:690` — the three that had `main` red, all
#: of them attributions of `NotificationType` members and of no column this table governs. The
#: fourth is `sdd/specs/rule11-ownership-guard.md:11`, the paragraph of this change's own new spec
#: that says the contract does **not** live there: it fires `censo` plus `quién la escribe` while
#: attributing nothing. **Zero true positives in scope, four false ones.** That is what decided D3.
#:
#: The fourth one is worth stating plainly rather than folding into the count, because it is the
#: uncomfortable half: **the spec this change adds is green only because of the narrowing this
#: change makes.** Under the old term set, writing a spec that declares where the contract lives
#: would have reddened the guard — which is the same self-reference that forced the roadmap entry
#: of this change to be reworded before D3 existed, and the concrete reason the meta-vocabulary
#: had to go rather than merely being a tidy-up.
#:
#: The total is given loosely on purpose. It counts the excluded trees, and `sdd/changes/` holds
#: the documents of every change in flight — including this one, whose own proposal and tasks
#: discuss the guard and therefore match the meta-vocabulary. It moved **twice while this change
#: was being written**, by its own writing. A number that its own recording changes is a number to
#: state as a magnitude, not as a census — so this one is stated as one, and the in-scope figure
#: **enumerated above** is what to hold it to. No numeral is repeated here on purpose: this very
#: sentence carried a stale one through two review rounds, because whoever recounted the paragraph
#: above did not think to recount its neighbour. The figure that binds is asserted by
#: `test_the_declared_cost_of_dropping_the_meta_vocabulary_is_still_what_the_prose_says`, which
#: pins the exact `file:line` set and not just the total — read that if this prose and the tree
#: ever disagree. What comes out with them
#: is stated as residual 5c of `test_what_this_guard_does_not_catch`, and it costs zero blocks in
#: scope today. **Re-measure against the tree before trusting any of these numbers**: they depend
#: on the tree, which is the property that made the previous version of this comment go stale.
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
    # `tech-cycle-completion` (2026-08-22) added one column to the census, and it goes in here
    # for residual 3's reason, the same one `incidents.assignment_note` above entered on: the
    # sink axis is fed by this tuple, so a column the table governs and this does not is a
    # blind spot the green would hide. Qualified with its table, like its two siblings and for
    # the identical reason — `incidents` is an ordinary English word all over this tree's prose.
    "incidents.materials",
    "properties.access_notes",
    "messages.content",
    "messages.intent",
    "messages.metadata",
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


# --- views over the scope -----------------------------------------------------------------


def entries(scope: tuple[ScopeEntry, ...], kind: Kind) -> tuple[ScopeEntry, ...]:
    return tuple(entry for entry in scope if entry.kind == kind)


def authority_path(scope: tuple[ScopeEntry, ...]) -> str:
    found = entries(scope, Kind.AUTHORITY)
    if len(found) != 1:
        raise GuardError(
            f"the scope declares {len(found)} authority entries; there is exactly one table and "
            "it is the referent every other entry is measured against"
        )
    return found[0].path


def excluded_paths(scope: tuple[ScopeEntry, ...]) -> tuple[str, ...]:
    return tuple(entry.path for entry in entries(scope, Kind.OUT_OF_CENSUS))


def exception_paths(scope: tuple[ScopeEntry, ...]) -> tuple[str, ...]:
    return tuple(entry.path for entry in entries(scope, Kind.EXCEPTION))


def validate_scope(scope: tuple[ScopeEntry, ...], root: Path) -> None:
    """Fail closed on a scope that would make the scan silently narrow.

    An empty `SCOPE`, or a census root that does not resolve, walks zero files and reports zero
    offenders — a green that means "we could not look". That is the worst failure this guard has,
    because it is the silent one.
    """
    if not scope:
        raise GuardError(
            "the scope is empty, so the scan would walk no file at all and report no offender. "
            "A guard with nothing in scope is not a green, it is a guard that did not run"
        )
    for entry in scope:
        if not entry.reason.strip():
            raise GuardError(
                f"the scope entry `{entry.path}` ({entry.kind}) has no reason written. An entry "
                "without a motive is one anyone can widen unnoticed"
            )
    authority_path(scope)
    for entry in scope:
        if entry.kind not in (Kind.AUTHORITY, Kind.CENSUS_PROSE, Kind.CENSUS_CODE):
            continue
        target = root / entry.path
        if entry.kind == Kind.AUTHORITY and not target.is_file():
            raise GuardError(
                f"the authority `{entry.path}` is not a file under {root}: the rule 11 table is "
                "the referent, so without it the guard is not measuring what it claims"
            )
        if entry.kind != Kind.AUTHORITY and not target.is_dir():
            raise GuardError(
                f"the census tree `{entry.path}` ({entry.kind}) does not exist under {root}, so "
                "everything below it would go unscanned while the guard stayed green. This is "
                "what an incomplete checkout looks like"
            )
    assert_no_dead_entry(scope, root)


def assert_no_dead_entry(scope: tuple[ScopeEntry, ...], root: Path) -> None:
    """R2.4, in the guard itself and not only in its suite.

    R2.4 says the SYSTEM reddens naming a dead entry, and `make check-rule11-ownership` is the
    system as much as `pytest scripts/` is. Leaving this to the suite alone meant the local path
    — the one R1.3 names — went green on an exemption that exempts nothing, which is the most
    dangerous of the three kinds because it skips a whole file.

    What is checked here is **resolution**: that the entry still corresponds to a path the scan
    reaches. Whether an exemption still *earns* its place — still contains something the guard
    would report — stays in the suite, because that is a judgement about content and it needs the
    whole scan to answer.
    """
    walked = {relative for relative, _ in prose_files(scope, root) + code_files(scope, root)}
    census = tuple(
        entry.path
        for entry in scope
        if entry.kind in (Kind.CENSUS_PROSE, Kind.CENSUS_CODE)
    )

    # Three checks per census tree, in order of cause, because collapsing them would report the
    # wrong diagnosis: the tree is missing (checked above), the tree holds none of the files its
    # kind is about (a wrong path, or a checkout that brought the directory and not its
    # contents), or the tree holds them and an exclusion is swallowing them.
    for kind, suffix in ((Kind.CENSUS_PROSE, ".md"), (Kind.CENSUS_CODE, ".py")):
        for entry in entries(scope, kind):
            if not any((root / entry.path).glob(f"**/*{suffix}")):
                raise GuardError(
                    f"the census tree `{entry.path}` ({entry.kind}) holds no `{suffix}` file at "
                    "all, so its whole subtree would go unscanned while the guard stayed green"
                )

    # A census tree that contributes nothing **after exclusions** is as dead as one that does
    # not exist, and it is the dangerous direction: an `OUT_OF_CENSUS` entry naming a whole
    # census tree removes it from the scan while the tree is still on disk, so every existence
    # check passes and the summary still NAMES it as census. Measured: excluding `backend/app`
    # takes the walk from 801 Python files to 408 and reports zero offenders — half the code
    # corpus, including the two model docstrings whose drift is why this guard exists. The
    # emptiness check below cannot see it, because it globs the raw tree without applying
    # exclusions; only the walked set can.
    for entry in scope:
        if entry.kind not in (Kind.CENSUS_PROSE, Kind.CENSUS_CODE):
            continue
        if not any(relative.startswith(entry.path + "/") for relative in walked):
            raise GuardError(
                f"the census tree `{entry.path}` ({entry.kind}) contributes no file to the "
                "scan, so everything it was meant to cover is unwatched. It exists on disk, so "
                "this is an exclusion swallowing it whole rather than a missing checkout"
            )

    for entry in entries(scope, Kind.OUT_OF_CENSUS):
        if not (root / entry.path).exists():
            raise GuardError(
                f"`{entry.path}` is excluded but no longer exists under {root}: the entry is "
                "dead. Delete it, or follow the tree if it moved"
            )
        if not any(entry.path == base or entry.path.startswith(base + "/") for base in census):
            raise GuardError(
                f"`{entry.path}` is excluded but lies outside every census tree, so it excludes "
                "nothing. A decorative exclusion hides that the path is unscanned for some other "
                "reason"
            )

    for entry in entries(scope, Kind.EXCEPTION):
        if entry.path not in walked:
            raise GuardError(
                f"`{entry.path}` is exempted but the scan no longer walks it: the entry is dead "
                "and exempts nothing. Delete it, or follow the file if it moved"
            )


def check_tree_is_visible(scope: tuple[ScopeEntry, ...], root: Path) -> int:
    """Fail-closed, and never `skip`.

    Kept from the container era, where a bind mount whose source was missing arrived as an empty
    directory. On the host the shape is a shallow or partial checkout, and the failure mode is
    identical: the scan walks nothing and reports success. `skip` would be almost as bad — in
    `-rs` output it reads as "did not apply", which is exactly the wrong thing for a security
    control to say when its input has vanished.
    """
    validate_scope(scope, root)

    authority = root / authority_path(scope)
    text = read(authority, authority_path(scope))
    if TABLE_HEADER not in text:
        raise GuardError(
            f"{authority} does not contain the rule 11 table header. Either the table moved or "
            "the checkout is not the one this guard expects; either way it is not measuring "
            "what it claims"
        )

    scanned = len(prose_files(scope, root))
    if scanned < MINIMUM_MARKDOWN_FILES:
        raise GuardError(
            f"only {scanned} Markdown files are visible, below the {MINIMUM_MARKDOWN_FILES} this "
            "tree should have. An incomplete checkout looks exactly like this — the scan is "
            "walking something, just not everything"
        )
    code = len(code_files(scope, root))
    if code < MINIMUM_PYTHON_FILES:
        raise GuardError(
            f"only {code} Python files are visible, below the {MINIMUM_PYTHON_FILES} this tree "
            "should have. Same failure as the Markdown floor above, on the half of the corpus "
            "that had no floor at all until it was measured"
        )

    return scanned


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


def _python_blocks(text: str, *, source: str = "<unknown>") -> list[tuple[int, str]]:
    """Docstrings, plus runs of contiguous `#` comments.

    Only prose: a block of code that happens to mention a column name is not a declaration of
    ownership, and reporting it would be the false-positive flood the two axes exist to avoid.
    """
    blocks: list[tuple[int, str]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        # Fail closed, for the same reason the checkout has a sentinel: "we could not look" must
        # never be reported as "there was nothing there".
        raise GuardError(
            f"the guard could not parse a file it is meant to scan: {source}: {error}"
        ) from error

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


def _offending_blocks(
    text: str, *, python: bool, source: str = "<unknown>"
) -> list[tuple[int, str, str]]:
    blocks = _python_blocks(text, source=source) if python else _markdown_blocks(text)
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


def _is_excluded(relative: str, scope: tuple[ScopeEntry, ...]) -> bool:
    return any(
        relative == path or relative.startswith(path + "/") for path in excluded_paths(scope)
    )


def _walk(
    scope: tuple[ScopeEntry, ...], root: Path, kind: Kind, suffix: str
) -> list[tuple[str, Path]]:
    authority = authority_path(scope)
    found: list[tuple[str, Path]] = []
    for entry in entries(scope, kind):
        base = root / entry.path
        for path in sorted(base.glob(f"**/*{suffix}")):
            relative = path.relative_to(root).as_posix()
            if relative == authority or _is_excluded(relative, scope):
                continue
            found.append((relative, path))
    return found


def prose_files(
    scope: tuple[ScopeEntry, ...] = SCOPE, root: Path = REPO_ROOT
) -> list[tuple[str, Path]]:
    return _walk(scope, root, Kind.CENSUS_PROSE, ".md")


def code_files(
    scope: tuple[ScopeEntry, ...] = SCOPE, root: Path = REPO_ROOT
) -> list[tuple[str, Path]]:
    return _walk(scope, root, Kind.CENSUS_CODE, ".py")


def offenders(
    scope: tuple[ScopeEntry, ...] = SCOPE, root: Path = REPO_ROOT
) -> list[tuple[str, int, str, str]]:
    """Every block outside the table that names a sink AND says who writes it."""
    exempt = set(exception_paths(scope))
    reported: list[tuple[str, int, str, str]] = []
    for relative, path in prose_files(scope, root) + code_files(scope, root):
        if relative in exempt:
            continue
        for line, phrase, excerpt in _offending_blocks(
            read(path, relative), python=path.suffix == ".py", source=relative
        ):
            reported.append((relative, line, phrase, excerpt))
    return reported


REMEDY = (
    "Ownership of a sink is declared in the rule 11 table of `sdd/steering/security.md`, and "
    "nowhere else — that is what rule 11 means by living in one place. Keep here what is local "
    "(that the column is a cleartext sink, that its contract is rule 11, why it is dangerous in "
    "THIS module, and the mechanism that enforces it if it lives here); move who writes it, or "
    "who will inherit it, to the table. If this block is a legitimate exception, add it to "
    "`SCOPE` in `scripts/rule11-ownership.py` as an `EXCEPTION` entry with its reason written "
    "out."
)


def render(reported: list[tuple[str, int, str, str]]) -> str:
    """File, line and the exact phrase that fired the axis — one block per finding."""
    blocks = [
        "\n".join(
            [
                f"fichero: {relative}:{line}",
                f"frase: {phrase!r}",
                f"bloque: {excerpt}",
            ]
        )
        for relative, line, phrase, excerpt in reported
    ]
    return (
        "these blocks name a rule 11 sink AND say who writes it:\n\n"
        + "\n\n".join(blocks)
        + f"\n\ninfractores: {len(reported)}\n\n{REMEDY}\n"
    )


def summary(scope: tuple[ScopeEntry, ...], root: Path, markdown: int) -> str:
    """The green NAMES and COUNTS what it walked, so it reads as "it looked at this"."""
    lines = [f"raíz: {root}"]
    for kind in Kind:
        for entry in entries(scope, kind):
            lines.append(f"{kind}: {entry.path}")
    lines.append(f"ficheros markdown recorridos: {markdown}")
    lines.append(f"ficheros python recorridos: {len(code_files(scope, root))}")
    lines.append(
        "veredicto: ningún bloque fuera de la tabla de la regla 11 declara quién escribe un "
        "sumidero del censo"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    """Validate the scope, walk it, decide, print. Never green on a broken chain."""
    try:
        markdown = check_tree_is_visible(SCOPE, REPO_ROOT)
        reported = offenders(SCOPE, REPO_ROOT)
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if reported:
        print(render(reported), end="")
        return 1

    print(summary(SCOPE, REPO_ROOT, markdown), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
