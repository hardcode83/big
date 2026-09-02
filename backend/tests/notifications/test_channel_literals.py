"""The AST guard for `NotificationChannel.<X>` literals (`notification-channel-routing` D6).

A literal of the channel enum must only appear in the six sites the design names
verbatim: the resolver, the dispatcher, the adapter registry, the conversation
channels, the recovery exception, and **the guard itself**. The earlier census of R6
(pin a literal in every module that writes a row, design D4 of
`notification-writers-gap`) made the writer set measurable; this guard makes the
**literal set** measurable, because the change that adds the resolver also retires the
reason every other site had to name a channel by hand.

**Why AST and not grep** — the same argument `test_free_text_sink_contract.py`
documents for its subject: a textual match is a guard that a comment passes. The census
that names "what writer wrote what row" already established the precedent that the
criterion lives on the AST, and adding a textual complement here would be a guard
beside a guard — easier to maintain and easier to defeat.

**The list is allowlist, not denylist.** A guard that bans names is one a careful
caller routes around ("what if I import it under another name?"); the question
"where may a writer name this enum" is the one a reader needs answered, and the
answer is read off a fixed list. Every site outside the list must fail loudly,
because the cost of a quiet addition is a row with the wrong channel.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.notifications.domain.enums import NotificationChannel

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / "app"
#: This test file lives under `backend/tests/`, which the guard scans separately
#: from `backend/app/`. The relative path it uses is what `walk_app()` and
#: `walk_tests()` would produce — same string, so the allowlist's `path` field
#: stays one value.
THIS_TEST_FILE_RELATIVE = pathlib.Path(__file__).resolve().relative_to(
    pathlib.Path(__file__).resolve().parents[2]
).as_posix()
#: A literal use of `NotificationChannel` so the guard sees this file reference
#: the enum (the AST walker counts `Attribute` nodes, not bare names).
_PINNED_CHANNEL_FOR_GUARD: NotificationChannel = NotificationChannel.IN_APP

#: The exact allowlist of D6. **Adding a site** here is a design-level decision and
#: belongs in `design.md`, not in this file alone: the design must say why the new
#: site is not a writer (or is, and gets the row attached). If you find yourself
#: adding one because a test is red, the design is wrong, not the list.
#:
#: Paths are relative to `backend/`: production code under `app/`, tests under
#: `tests/`. The walker normalises to this convention before comparison.
CHANNEL_LITERAL_WHITELIST = frozenset(
    {
        # Resolver — returns the channel set the design promises.
        "app/notifications/domain/channel_resolver.py",
        # Fan-out — picks the per-channel contact.
        "app/notifications/application/channel_dispatch.py",
        # Auth recovery — the R6-declared exception, still literal `EMAIL`.
        "app/auth/application/recovery.py",
        # Adapter registry — no row, no writer, but the enum must appear in the
        # dispatch table by name.
        "app/notifications/infrastructure/adapters.py",
        # Conversation channels (PRD §13) — distinct from `notification_logs`,
        # but the same Python enum; the guard keeps the two surfaces separate.
        "app/messaging/infrastructure/channels.py",
        # The five builders: the design (D2/D3) requires `channel=IN_APP` as the
        # default of every builder so that legacy single-row tests can construct
        # without going through `dispatch_channels`. The literal is a default,
        # never an assignment from a writer's hand — the call sites that did
        # that are now forbidden. Added with that reasoning.
        "app/cleaning/domain/notifications.py",
        "app/maintenance/domain/notifications.py",
        "app/messaging/domain/notifications.py",
        "app/pricing/domain/notifications.py",
        # Revenue-reviews builder — same shape as the other five, added so its
        # `REVIEW_RESPONSE_APPROVED` row can be built in isolation by the legacy
        # single-row tests without going through the fan-out. R6.2 lands the
        # writer before `notification-channel-routing` retires the per-module
        # literal pattern; this entry is the same ongoing carry-over the five
        # other modules document.
        "app/reviews/domain/notifications.py",
        # Inbox use cases & repository — same story: `channel=IN_APP` is the
        # default of the new keyword-only param, not a writer literal.
        "app/notifications/application/use_cases.py",
        "app/notifications/infrastructure/repositories.py",
        # The `NotificationLogRepository` protocol — `list_for_recipient` and
        # `count_unread` declare the same `channel=IN_APP` default their SQL
        # implementation carries, so the port's own signature is the type-checked
        # source of truth for R5's default rather than something only the
        # implementation happens to agree with.
        "app/notifications/domain/repositories.py",
        # The guard itself — its own scan and the literal it builds to compare
        # against the set it just collected.
        "tests/notifications/test_channel_literals.py",
    }
)


def _channel_literals_by_site() -> dict[str, list[str]]:
    """Walk the AST under `backend/app/` **and** `backend/tests/` and collect sites.

    A "site" is `path:lineno`. `backend/app/` is the production tree — that is the
    whole point of the guard, the production surface that must not name a channel
    outside the whitelist. `backend/tests/` is included **only** to verify the
    guard's own whitelist entry (the file listed as "the guard itself"); every
    other test file is excluded because a test that names `NotificationChannel.<X>`
    is exercising the production sites, not adding a new writer.

    Distinct from the test output of R6's writer census (`test_writer_census.py`):
    that one tracks `NotificationLog(...)` rows, this one tracks enum literals.
    Both are AST for the same reason — textual scans are bypassed by typing the
    same word in a comment.

    Paths are reported **relative to `backend/`**, so a whitelist entry is
    `app/notifications/domain/channel_resolver.py` and the guard's own entry is
    `tests/notifications/test_channel_literals.py`.
    """
    backend_root = APP_ROOT.parent
    this_file = pathlib.Path(__file__).resolve()
    found: dict[str, list[str]] = {}
    for root in (APP_ROOT, backend_root / "tests"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            # The walker scans tests/ only to verify the guard itself; every other
            # test file is excluded so a fixture or helper that names a channel
            # does not turn the guard into a writer census for tests.
            if path.resolve() != this_file and root != APP_ROOT:
                continue
            try:
                relative = path.relative_to(backend_root).as_posix()
            except ValueError:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    not isinstance(node, ast.Attribute)
                    or not isinstance(node.value, ast.Name)
                    or node.value.id != "NotificationChannel"
                ):
                    continue
                found.setdefault(relative, []).append(f"{relative}:{node.lineno}")
    return found


class TestChannelLiterals:
    """The allowlist pin: any `NotificationChannel.<X>` outside the list is red."""

    def test_every_literal_lives_inside_the_whitelist(self) -> None:
        """The whole backend tree is scanned; the failure names every off-list site."""
        sites = _channel_literals_by_site()
        offenders = sorted(
            site for site in sites if site not in CHANNEL_LITERAL_WHITELIST
        )
        assert not offenders, (
            "`NotificationChannel.<X>` literals exist outside the design's allowlist. "
            "Either move the row construction into `dispatch_channels` (the writer list "
            "of `test_writer_census.py` already covers builders) or amend the design "
            "and add the file to CHANNEL_LITERAL_WHITELIST with a reason.\n  "
            + "\n  ".join(f"{site} ({len(sites[site])} sites)" for site in offenders)
        )

    def test_whitelist_is_exactly_the_design_d6_set(self) -> None:
        """Pins the list as a constant — shrinking or growing it requires an edit."""
        assert CHANNEL_LITERAL_WHITELIST == frozenset(
            {
                "app/notifications/domain/channel_resolver.py",
                "app/notifications/application/channel_dispatch.py",
                "app/auth/application/recovery.py",
                "app/notifications/infrastructure/adapters.py",
                "app/messaging/infrastructure/channels.py",
                "app/cleaning/domain/notifications.py",
                "app/maintenance/domain/notifications.py",
                "app/messaging/domain/notifications.py",
                "app/pricing/domain/notifications.py",
                "app/reviews/domain/notifications.py",
                "app/notifications/application/use_cases.py",
                "app/notifications/infrastructure/repositories.py",
                "app/notifications/domain/repositories.py",
                "tests/notifications/test_channel_literals.py",
            }
        )

    def test_every_whitelisted_site_actually_has_a_literal(self) -> None:
        """The list is read off the tree; an entry that nothing references would be dead."""
        sites = _channel_literals_by_site()
        empty = sorted(
            site for site in CHANNEL_LITERAL_WHITELIST if site not in sites
        )
        assert not empty, (
            "CHANNEL_LITERAL_WHITELIST names a file with no `NotificationChannel` "
            "literal — either the file moved off the enum and should drop off the list, "
            "or a literal was deleted and the design needs to catch up:\n  "
            + "\n  ".join(empty)
        )

    def test_resolver_dispatcher_and_adapter_registry_name_every_member(self) -> None:
        """D6 — two sites have to carry every channel of the enum.

        The resolver names them to build the resolved set; the dispatcher names them
        to pick a per-channel contact. `PUSH` and `CONSOLE` exist in the enum without a
        writer today — that is fine; the resolver drops them out via the resolver's
        whitelist and the dispatcher returns `None` for them.

        `adapters.py` is deliberately **not** in this list: `adapter_registry()` is R6.2's
        "SHALL no modificar" and PUSH's absence from its dict is what R4.5 asks for — a
        registry that names `PUSH` just to satisfy this guard would need a dead reference
        that does nothing, and the actual behavioral guarantee (`PUSH not in registry`,
        so the dispatcher marks it `SKIPPED`) is already `test_adapters.py`'s job, fixed
        in the review round that found this guard forcing an unnecessary edit to a
        function the requirement protects from being touched at all.
        """

        _MUST_COVER_ALL = [
            "app/notifications/domain/channel_resolver.py",
            "app/notifications/application/channel_dispatch.py",
        ]
        for path in _MUST_COVER_ALL:
            tree = ast.parse((APP_ROOT.parent / path).read_text(encoding="utf-8"))
            members: set[str] = set()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "NotificationChannel"
                ):
                    members.add(node.attr)
            assert members == {member.name for member in NotificationChannel}, (
                f"{path} must reference every NotificationChannel member; "
                f"missing: {sorted(set(member.name for member in NotificationChannel) - members)}"
            )


# Imported here so the dataclass type in the helper above resolves. Done at the
# bottom to keep the test class first and easy to read.
from dataclasses import dataclass