"""`render_access_instructions_email` (`guest-scheduled-comms` R3, R5, design D6).

Rule 11 of `steering/security.md`, exception 1: `notification_logs.subject`/`body` may carry
the masked `****XX` form of an access code and nothing else. These tests pin that the rendered
text is fixed prose plus that masked form — the same discipline
`tests/reservations/test_notifications.py` pins for the check-in/check-out reminders.
"""

from app.access.domain.notifications import (
    _ACCESS_INSTRUCTIONS_BODY,
    render_access_instructions_email,
)

CODE_MASKED = "****42"


def test_the_spanish_template_is_returned_by_default_language() -> None:
    subject, body = render_access_instructions_email("es", CODE_MASKED)

    assert subject.strip()
    assert body.strip()
    assert CODE_MASKED in body


def test_the_english_template_is_a_different_text() -> None:
    es_subject, es_body = render_access_instructions_email("es", CODE_MASKED)
    en_subject, en_body = render_access_instructions_email("en", CODE_MASKED)

    assert en_subject != es_subject
    assert en_body != es_body
    assert CODE_MASKED in en_body


def test_an_unrecognised_language_falls_back_to_spanish() -> None:
    for unrecognised in ("fr", "", "ES", "en-US", "not-a-language"):
        assert render_access_instructions_email(unrecognised, CODE_MASKED) == (
            render_access_instructions_email("es", CODE_MASKED)
        )


def test_the_subject_fits_the_column() -> None:
    """`notification_logs.subject` is `String(500)`."""
    for language in ("es", "en"):
        subject, _ = render_access_instructions_email(language, CODE_MASKED)
        assert len(subject) <= 500


def test_different_masked_codes_produce_different_bodies() -> None:
    """The only guest-visible variable is the masked code (R3.1) — changing it must change the
    rendered body."""
    _, base_body = render_access_instructions_email("es", CODE_MASKED)
    _, other_body = render_access_instructions_email("es", "****99")

    assert other_body != base_body


def test_only_the_masked_form_appears_nothing_else_from_the_record() -> None:
    """R3.2 — only the fixed template plus `code_masked` ever reach the rendered text.

    Asserted against the module's own private template dict, so a future edit to the prose
    still keeps this test meaningful: the rendered body must be EXACTLY the fixed template with
    `code_masked` substituted in, never that template plus something extra a caller slipped in
    (`access_records.notes` or any other free text) — because nothing but `code_masked` is ever
    a parameter of this function in the first place.
    """
    forbidden_free_text = "left the key under the mat, gate code 1234"
    for language in ("es", "en"):
        _, body = render_access_instructions_email(language, CODE_MASKED)
        assert forbidden_free_text not in body
        assert body == _ACCESS_INSTRUCTIONS_BODY[language].format(code_masked=CODE_MASKED)
