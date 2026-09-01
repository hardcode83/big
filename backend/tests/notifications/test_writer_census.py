"""Which `NotificationType`s have a writer, measured rather than remembered (R6, design D9).

The census this file replaces was done by hand, twice, and was wrong both times: the roadmap
note said nine types had no writer, and `notification-writers-gap`'s own proposal found ten by
counting again. A number in prose is a number that rots — so this measures the tree instead.

**What counts as a writer, and why the callee is pinned.** Exactly two forms, per R6.3:

  (a) a call whose callee is literally `NotificationLog`, with
      `notification_type=NotificationType.<X>.value`; and
  (b) a call whose callee is literally `Escalation`, with
      `notification_type=NotificationType.<X>` — no `.value` — in
      `notifications/domain/escalation.py`.

Fixing the callee is not decoration. The obvious rule — "look for
`notification_type=NotificationType.<X>.value` anywhere" — is wrong in **both** directions,
and the design measured how:

- It counts too much. That keyword appears in four calls to `cancel_sla_deadline`
  (`cleaning/application/use_cases.py`, and three in `maintenance/application/use_cases.py`)
  which **clear a deadline and write nothing**. Without the callee, `CLEANING_TASK_ASSIGNED`
  and `TECHNICIAN_ASSIGNED` would keep counting as written even if their builders were
  deleted.
- It counts too little. `SLA_BREACH` has no literal in any `NotificationLog(...)`: its row is
  composed by `_escalation_row` from the policy map, as `escalation.notification_type.value`.
  Form (b) is what sees it — and, since `notification-writers-gap` R3, `TECHNICIAN_NO_RESPONSE`
  too.

With the naive form, `WITHOUT_WRITER` below would have to list six names instead of four, and
R6.2 would contradict itself.

**AST and not `grep`**, for the reason `test_free_text_sink_contract.py` documents about its
own subject: a guard that reads text is a guard you pass by writing the right words in a
comment. Nothing here is satisfied by prose.

The two free-text types that are not enum members — `INCIDENT_REJECTED` and
`LEGAL_REGISTRATION_FAILED` — are out of scope by construction: there is no
`NotificationType.<X>` for either, so neither form can match them.
"""

import ast
import pathlib

import pytest

from app.notifications.domain.enums import NotificationType

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / "app"

#: The enum's own module is excluded: it declares every member, and a declaration is not a
#: writer. Including it would make the census say everything is written.
EXCLUDED = {"notifications/domain/enums.py"}

#: The file form (b) is allowed to appear in. The escalation policy is the only place in the
#: codebase that names a type without `.value`, and confining the form to it stops a future
#: `Escalation(...)` built somewhere else from silently joining the census.
ESCALATION_MODULE = "notifications/domain/escalation.py"

#: Types with a production writer, as of `notification-writers-gap`. Thirteen.
#:
#: Seven predate this change — `CLEANING_TASK_ASSIGNED`, `CLEANING_NO_RESPONSE`,
#: `TECHNICIAN_ASSIGNED`, `OWNER_APPROVAL_REQUIRED`, `GUEST_ESCALATION`,
#: `PASSWORD_RESET_REQUESTED` and `SLA_BREACH` — and six are its own.
WITH_WRITER = frozenset(
    {
        "CLEANING_TASK_ASSIGNED",
        "CLEANING_NO_RESPONSE",
        "CLEANING_COMPLETED",
        "CLEANING_FAILED",
        "INCIDENT_CREATED_CRITICAL",
        "INCIDENT_CREATED_HIGH",
        "OWNER_APPROVAL_REQUIRED",
        "TECHNICIAN_ASSIGNED",
        "TECHNICIAN_NO_RESPONSE",
        "GUEST_ESCALATION",
        "PRICE_RECOMMENDATION",
        "SLA_BREACH",
        "PASSWORD_RESET_REQUESTED",
    }
)

#: Types nothing writes, and the change that owes each one (R6.2). Four.
#:
#: `LOCK_ALERT` wants a lock-import surface that does not exist
#: (`maintenance/api/incidents_router.py` says so). The three guest reminders belong to
#: `guest-scheduled-comms`: `send_checkin_reminders` is one of PRD §8.3's jobs and has no
#: code, and there is no channel to the guest until it does.
WITHOUT_WRITER = frozenset(
    {
        "LOCK_ALERT",
        "CHECKIN_REMINDER_24H",
        "CHECKIN_REMINDER_2H",
        "CHECKOUT_REMINDER",
    }
)


def _member_named(node: ast.expr) -> str | None:
    """`NotificationType.<X>` → `"<X>"`, anything else → `None`."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "NotificationType"
    ):
        return node.attr
    return None


def _writers() -> dict[str, list[str]]:
    """Every type with a writer, mapped to the sites that write it.

    Sites are carried so a failure can name a file and a line instead of only a set
    difference — the same courtesy `test_layering.py` and `test_rule11_ownership.py` extend.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        relative = path.relative_to(APP_ROOT).as_posix()
        if relative in EXCLUDED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            callee = node.func.id
            if callee not in {"NotificationLog", "Escalation"}:
                continue
            for keyword in node.keywords:
                if keyword.arg != "notification_type":
                    continue
                if callee == "NotificationLog":
                    # Form (a): `NotificationType.<X>.value`.
                    value = keyword.value
                    if not (isinstance(value, ast.Attribute) and value.attr == "value"):
                        continue
                    member = _member_named(value.value)
                else:
                    # Form (b): `NotificationType.<X>`, bare, and only in the policy module.
                    if relative != ESCALATION_MODULE:
                        continue
                    member = _member_named(keyword.value)
                if member is not None:
                    found.setdefault(member, []).append(f"{relative}:{node.lineno}")
    return found


def test_the_two_lists_partition_the_enum() -> None:
    """R6.4 — a member that is in neither list breaks the build.

    This is what stops the census from rotting: a type added to `NotificationType` without a
    decision about whether anything writes it cannot pass silently, which is precisely how
    the previous count went wrong.
    """
    members = {member.value for member in NotificationType}

    assert WITH_WRITER | WITHOUT_WRITER == members
    assert not (WITH_WRITER & WITHOUT_WRITER)


def test_exactly_four_types_have_no_writer() -> None:
    """R6.2 — the list is literal, so shrinking it requires saying which type gained a writer."""
    assert WITHOUT_WRITER == {
        "LOCK_ALERT",
        "CHECKIN_REMINDER_24H",
        "CHECKIN_REMINDER_2H",
        "CHECKOUT_REMINDER",
    }


def test_the_measured_writers_are_exactly_the_declared_ones() -> None:
    """R6.1/R6.3, asserted in **both** directions.

    One direction alone is half a guard: comparing only "declared ⊆ measured" would miss a
    writer that quietly appeared, and only "measured ⊆ declared" would miss one that quietly
    vanished. The failure names the sites, so a red build points at a file rather than at a
    set.
    """
    measured = _writers()

    missing = sorted(WITH_WRITER - measured.keys())
    unexpected = sorted(measured.keys() - WITH_WRITER)

    assert not missing, (
        "declared as written, but no writer found in `backend/app/`: "
        + ", ".join(missing)
        + ". Either the writer was removed — in which case move the type to "
        "`WITHOUT_WRITER` and say why — or it stopped matching one of R6.3's two forms."
    )
    assert not unexpected, (
        "these types are written but not declared: "
        + "; ".join(f"{name} at {', '.join(measured[name])}" for name in unexpected)
        + ". Add them to `WITH_WRITER`."
    )


def test_every_orphan_really_has_no_writer() -> None:
    """The other half of R6.2: the four are measured to be absent, not assumed to be."""
    measured = _writers()

    still_written = sorted(WITHOUT_WRITER & measured.keys())

    assert not still_written, (
        "declared as having no writer, but one exists: "
        + "; ".join(f"{name} at {', '.join(measured[name])}" for name in still_written)
    )


# --- 7.3: the guard has to discriminate, so prove it does ------------------------------


def test_clearing_a_deadline_is_not_writing_a_notification() -> None:
    """The over-counting half of D9, pinned against the real call sites.

    `cancel_sla_deadline(..., notification_type=NotificationType.<X>.value)` carries the exact
    keyword this census looks for, and writes nothing. If the callee constraint were dropped,
    these calls would keep `CLEANING_TASK_ASSIGNED` and `TECHNICIAN_ASSIGNED` in the census
    even with their builders deleted — so this test asserts the calls still exist **and** that
    the census does not reach them.
    """
    sources = {
        path.relative_to(APP_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in APP_ROOT.rglob("*.py")
    }
    cancels = [
        (relative, node.lineno)
        for relative, text in sources.items()
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "cancel_sla_deadline"
        and any(
            keyword.arg == "notification_type"
            and isinstance(keyword.value, ast.Attribute)
            and keyword.value.attr == "value"
            and _member_named(keyword.value.value) is not None
            for keyword in node.keywords
        )
    ]

    # The premise: such calls exist. If they ever stop existing this test should be revisited
    # rather than silently passing on an empty set.
    assert cancels, "no `cancel_sla_deadline` call carries a NotificationType any more"

    measured_sites = {site for sites in _writers().values() for site in sites}
    for relative, line in cancels:
        assert f"{relative}:{line}" not in measured_sites


@pytest.mark.parametrize("member", ["SLA_BREACH", "TECHNICIAN_NO_RESPONSE"])
def test_the_escalation_policy_counts_as_a_writer(member: str) -> None:
    """The under-counting half of D9.

    Neither type has a literal in any `NotificationLog(...)`: both are produced by the policy
    map and written by `_escalation_row` through `escalation.notification_type.value`. Form
    (b) is the only thing that sees them, and without it R6.2 would have to declare six
    orphans instead of four.
    """
    measured = _writers()

    assert member in measured
    assert all(site.startswith(ESCALATION_MODULE) for site in measured[member])


# --- The census matches by NAME, so pin what makes that sound -------------------------
#
# Raised by the section-6/7 security panel, which measured that the guard above recognises a
# writer only by identifier: an aliased import, a qualified callee, a `**kwargs` expansion or
# a positional argument would each make a real writer invisible, and the type would then be
# recorded as an orphan — the exact rot the census exists to stop, wearing the census's own
# authority. It measured zero live instances of any of them; these three tests are what keep
# that true, by fixing the shape and the scope instead of trusting the name.

#: Every module allowed to construct a notification row or an escalation policy entry.
#:
#: An allowlist and not a prohibition, because a guard that bans names is one somebody routes
#: around: the question "who can write this sink" has to be answerable by reading a list, and
#: a construction site outside it must fail loudly rather than quietly widen the surface.
CONSTRUCTION_SITES = {
    # The pure builders — the intended home of every row.
    "cleaning/domain/notifications.py",
    "maintenance/domain/notifications.py",
    "messaging/domain/notifications.py",
    "pricing/domain/notifications.py",
    # Two writers that predate the builder convention and compose their row inline.
    "auth/application/recovery.py",
    "guests/application/use_cases.py",
    # The escalation policy (its `Escalation` entries) and the row its use case composes.
    "notifications/domain/escalation.py",
    "notifications/application/use_cases.py",
    # The fan-out — the new construction site added by `notification-channel-routing`
    # (R2). It iterates the resolved channel set and calls a builder once per channel,
    # so it is a construction site of N rows, not of one. Added here for the same
    # reason as every other entry: the census counts writers, and the fan-out is one.
    "notifications/application/channel_dispatch.py",
    # Not a writer: the adapter's INSERT and its rehydration of a row back into an entity.
    "notifications/infrastructure/repositories.py",
    # Not a writer either, and not application code: the `celery-jobs` benchmark harness
    # seeds breach candidates into a dev database. Declared rather than excluded so that the
    # allowlist's own claim — rows are built only where the census can see them — is true of
    # the whole backend tree instead of only the part that happened to be swept.
    "scripts/measure_tenant_filter.py",
}

CONSTRUCTED_NAMES = {"NotificationLog", "NotificationLogModel", "Escalation"}

#: The names the census matches on. If any of them is ever imported under another name, the
#: AST match above silently stops seeing that module.
NAMES_THAT_MUST_NOT_BE_ALIASED = CONSTRUCTED_NAMES | {"NotificationType"}


def _swept_files() -> list[tuple[str, ast.Module]]:
    """`backend/app/` plus the migrations, which can insert rows too.

    `alembic/versions/` and `scripts/` are outside the census proper — neither a migration nor
    a benchmark harness is a *writer* in the sense R6 counts — but both are inside the
    allowlist check, because a data migration or a seeding script that constructs rows is
    exactly the kind of surface that would otherwise never be looked at.

    All three roots, and not just `app/`, because the claim this allowlist makes is "a
    notification row may only be built where the census can see it". The section-6/7 security
    panel's closure check found that claim was being enforced over two of the backend's three
    code roots while being stated over all of them — `scripts/measure_tenant_filter.py` builds
    rows and was in none of them. Stating an invariant more widely than you check it is how a
    guard ends up trusted for something it never verified.
    """
    backend_root = APP_ROOT.parent
    files = []
    for root in (APP_ROOT, backend_root / "alembic", backend_root / "scripts"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            # Relative to `backend/` for the migrations and to `app/` for the rest, so the
            # labels here read the same way as the census's own site strings.
            base = APP_ROOT if root == APP_ROOT else backend_root
            relative = path.relative_to(base).as_posix()
            files.append((relative, ast.parse(path.read_text(encoding="utf-8"))))
    return files


def test_no_alias_can_hide_a_writer_from_the_census() -> None:
    """Renaming a matched symbol would make the census blind to it.

    Two forms, because the panel's closure check named the second: `from ... import
    NotificationLog as Log`, and a plain rebinding `Log = NotificationLog` later in a module.
    Both were measured at zero; both are cheap to keep at zero. The third conceivable form,
    `import module as m` followed by `m.NotificationLog(...)`, needs no rule of its own — it
    is an attribute callee, which the construction-site test rejects outright.
    """
    offenders = []
    for relative, tree in _swept_files():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                offenders += [
                    f"{relative}:{node.lineno} — imported `{alias.name}` as `{alias.asname}`"
                    for alias in node.names
                    if alias.name in NAMES_THAT_MUST_NOT_BE_ALIASED and alias.asname
                ]
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
                if node.value.id in NAMES_THAT_MUST_NOT_BE_ALIASED:
                    offenders.append(
                        f"{relative}:{node.lineno} — rebound `{node.value.id}` to another name"
                    )

    assert not offenders, (
        "these rename a symbol the census matches by name, so the census can no longer see "
        "through them:\n  " + "\n  ".join(offenders)
    )


def test_every_construction_site_is_one_the_census_knows_about() -> None:
    """A row built anywhere else — or through an attribute callee — fails loudly.

    Catches both the qualified form (`entities.NotificationLog(...)`, which the census skips
    before it checks anything) and a brand-new module quietly gaining the ability to write.
    """
    offenders = []
    for relative, tree in _swept_files():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                name, qualified = node.func.id, False
            elif isinstance(node.func, ast.Attribute):
                name, qualified = node.func.attr, True
            else:
                continue
            if name not in CONSTRUCTED_NAMES:
                continue
            if qualified:
                offenders.append(
                    f"{relative}:{node.lineno} — `{name}` built through an attribute callee, "
                    "which the census cannot see"
                )
            elif relative not in CONSTRUCTION_SITES:
                offenders.append(
                    f"{relative}:{node.lineno} — `{name}` built outside CONSTRUCTION_SITES"
                )

    assert not offenders, (
        "notification rows may only be built where the census can see them:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither move the construction into a domain builder, or add the module to "
        "CONSTRUCTION_SITES **and** make sure the census's two forms match what it writes."
    )


def test_every_row_names_its_type_as_a_plain_keyword() -> None:
    """`NotificationLog(**payload)` and a positional type would both slip past the census.

    The census reads `node.keywords` looking for `notification_type`; a `**` expansion has no
    `arg` at all, and a positional argument is not in `keywords`. Requiring the keyword to be
    written out is what makes "the census saw every row" a true statement rather than a hope.
    """
    offenders = []
    for relative, tree in _swept_files():
        if relative not in CONSTRUCTION_SITES:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {"NotificationLog", "Escalation"}:
                continue
            # `notifications/infrastructure/repositories.py` rehydrates an entity out of a
            # model; that is a read, and it names every field explicitly anyway.
            if any(keyword.arg is None for keyword in node.keywords):
                offenders.append(f"{relative}:{node.lineno} — built with `**kwargs`")
            elif node.args:
                offenders.append(f"{relative}:{node.lineno} — built with positional arguments")
            elif not any(k.arg == "notification_type" for k in node.keywords):
                offenders.append(
                    f"{relative}:{node.lineno} — no explicit `notification_type=` keyword"
                )

    assert not offenders, (
        "every notification row must name its type as a written-out keyword, or the census "
        "cannot count it:\n  " + "\n  ".join(offenders)
    )
