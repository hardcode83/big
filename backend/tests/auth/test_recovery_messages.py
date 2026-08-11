"""The sent text and the stored text are two different things (R4.2, design D2).

Rule 11 of `steering/security.md` lets `notification_logs.subject`/`body` carry exactly one
sensitive value — the masked `****XX` form of an access code — and a live recovery link is
not it. These tests pin the separation that keeps that true.
"""

from app.auth.domain.recovery_messages import (
    RECOVERY_EMAIL_SUBJECT,
    STORED_RECOVERY_BODY,
    STORED_RECOVERY_SUBJECT,
    render_recovery_email,
)
from app.auth.domain.recovery_tokens import generate_recovery_token

LINK_BASE = "https://app.example.test/reset-password?token="


def test_the_sent_body_carries_the_link() -> None:
    token, _ = generate_recovery_token()
    link = LINK_BASE + token
    _, body = render_recovery_email(link)
    assert link in body


def test_the_sent_subject_says_what_the_mail_is_for() -> None:
    subject, _ = render_recovery_email(LINK_BASE + "irrelevant")
    assert subject == RECOVERY_EMAIL_SUBJECT
    assert subject.strip()


def test_the_stored_subject_and_body_never_contain_the_link_or_the_token() -> None:
    """The assertion R4.2 is about, checked against a real token rather than a literal."""
    for _ in range(50):
        token, token_hash = generate_recovery_token()
        link = LINK_BASE + token
        for stored in (STORED_RECOVERY_SUBJECT, STORED_RECOVERY_BODY):
            assert link not in stored
            assert token not in stored
            assert token_hash not in stored


def test_the_stored_body_shares_no_meaningful_substring_with_the_token() -> None:
    """Not just absent as a whole: no recoverable fragment either (R4.1, R4.3)."""
    for _ in range(50):
        token, _ = generate_recovery_token()
        for i in range(len(token) - 5):
            assert token[i : i + 6] not in STORED_RECOVERY_BODY
            assert token[i : i + 6] not in STORED_RECOVERY_SUBJECT


def test_the_stored_texts_are_constants_and_take_no_argument() -> None:
    """Structural, not a convention: there is no call that could render a link in there.

    A `render_stored_body(link)` would make the guarantee depend on every caller passing
    nothing; a constant cannot be handed a token at all (design D2).
    """
    assert isinstance(STORED_RECOVERY_SUBJECT, str)
    assert isinstance(STORED_RECOVERY_BODY, str)


def test_the_two_bodies_are_different_texts() -> None:
    _, sent_body = render_recovery_email(LINK_BASE + "irrelevant")
    assert sent_body != STORED_RECOVERY_BODY


def test_the_stored_subject_fits_the_column() -> None:
    """`notification_logs.subject` is `String(500)`."""
    assert len(STORED_RECOVERY_SUBJECT) <= 500


def test_the_stored_texts_say_something_an_operator_can_read() -> None:
    """The row still has to record that a notice happened (design D2)."""
    assert "reset" in STORED_RECOVERY_SUBJECT.lower()
    assert STORED_RECOVERY_BODY.strip()
