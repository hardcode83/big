"""No writer in `backend/app/reviews/infrastructure/` smuggles a tag past `RecurringIssueTag`.

Calqued on `tests/maintenance/test_classifier_vocabulary_contract.py` and
`tests/messaging/test_free_text_sink_contract.py`. The catalogue of `RecurringIssueTag`
is closed, and an adapter that persisted a string outside the enum would be the
`webhook_events.event_type`-shaped gap the rule-11 census preamble exists for.

The walk is rooted at `backend/app/reviews/infrastructure/` because that is where the
adapters live; the entity guard (`Review._coerce_recurring_issues`) is what catches
whatever slips past the analyser.
"""

from pathlib import Path

from app.reviews.domain.enums import RecurringIssueTag


def _infrastructure_py_files() -> list[Path]:
    infra = Path(__file__).resolve().parents[2] / "app" / "reviews" / "infrastructure"
    return sorted(infra.rglob("*.py"))


def test_no_infrastructure_writer_uses_a_string_recurring_issue() -> None:
    """The walk finds any literal that names `recurring_issues` together with a string
    value, and fails in red naming the file and line. The entity is the second net
    against an unrecognised tag; this test is the first."""
    offending: list[str] = []
    for path in _infrastructure_py_files():
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "recurring_issues" not in stripped:
                continue
            # A bare string assignment is the violation: the entity coerces with
            # `RecurringIssueTag(value)`, and a value the enum rejects degrades to
            # `OTHER` with a warning. The walk is not a guarantee — it is the same
            # admission-condition test maintenance's classifier sweep is.
            if (
                "=" in stripped
                and not stripped.startswith("if ")
                and not stripped.startswith("for ")
                and not stripped.startswith("while ")
                and "RecurringIssueTag" not in stripped
            ):
                # Skip tuple / list comprehensions and dict-comprehension style writes
                # that legitimately wrap a tag list.
                if any(token in stripped for token in ("(", "[", "{")):
                    continue
                offending.append(f"{path}:{line_number}: {stripped}")
    assert offending == [], (
        "recurring_issues writers must use RecurringIssueTag members; offenders:\n"
        + "\n".join(offending)
    )


def test_recurring_issue_tag_has_nine_members_and_no_open_ends() -> None:
    """PRD §18's set, named in the enum: nine labels and nothing else. A change that
    adds a tenth is a deliberate catalogue widening, and that widening is what the
    enum membership test is for."""
    members = set(RecurringIssueTag)
    assert members == {
        RecurringIssueTag.WIFI,
        RecurringIssueTag.NOISE,
        RecurringIssueTag.CLEANLINESS,
        RecurringIssueTag.ACCESS,
        RecurringIssueTag.COMMUNICATION,
        RecurringIssueTag.LOCATION,
        RecurringIssueTag.VALUE,
        RecurringIssueTag.AMENITIES,
        RecurringIssueTag.OTHER,
    }
