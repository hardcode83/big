"""`normalize_email` of the guests domain (design D8)."""

from app.guests.domain.value_objects import normalize_email


def test_it_strips_and_lowercases() -> None:
    assert normalize_email("  John.Smith@Example.COM ") == "john.smith@example.com"


def test_it_is_idempotent() -> None:
    once = normalize_email("John@Example.com")
    assert normalize_email(once) == once


def test_it_agrees_with_the_auth_definition() -> None:
    """The two copies exist for dependency reasons (see the module docstring), not to
    behave differently. If this ever fails, one of them drifted and that is the bug."""
    from app.auth.domain.value_objects import normalize_email as auth_normalize

    for value in ("  A@B.COM ", "already@lower.com", "MiXeD@Case.Org"):
        assert normalize_email(value) == auth_normalize(value)
