"""`render_stored_guest_link_notice` / `render_guest_link_delivery_email` (`guest-link-delivery`
R3.1/R3.4, design D6).

Rule 11 of `steering/security.md`: `notification_logs.subject`/`body` is a closed sink. These
tests pin that the *stored* guest-portal-link notice is constant text keyed only by language,
and that the *sent* email is a distinct text that actually carries the portal URL.
"""

from app.guests.domain.notifications import (
    render_guest_link_delivery_email,
    render_stored_guest_link_notice,
)


def test_the_spanish_template_is_returned_by_default_language() -> None:
    subject, body = render_stored_guest_link_notice("es")

    assert subject.strip()
    assert body.strip()


def test_the_english_template_is_a_different_text() -> None:
    es_subject, es_body = render_stored_guest_link_notice("es")
    en_subject, en_body = render_stored_guest_link_notice("en")

    assert en_subject != es_subject
    assert en_body != es_body


def test_an_unrecognised_language_falls_back_to_spanish() -> None:
    for unrecognised in ("fr", "", "ES", "en-US", "not-a-language"):
        assert render_stored_guest_link_notice(unrecognised) == render_stored_guest_link_notice(
            "es"
        )


def test_the_texts_are_constants_and_take_no_other_argument() -> None:
    """Structural, not a convention: the function signature has nowhere to put a guest name,
    a reservation id or a link — the same guarantee `render_recovery_email`'s docstring makes
    about its own stored (non-sent) constants, but here it covers the whole pair."""
    import inspect

    signature = inspect.signature(render_stored_guest_link_notice)

    assert list(signature.parameters) == ["language"]


def test_neither_template_contains_an_interpolation_hole() -> None:
    """A `{...}`/`%s`/f-string slot would be the mechanism by which a guest name, a
    reservation id or a link could later sneak in. There must be none to sneak into."""
    from app.guests.domain import notifications as module

    for mapping in (module._SUBJECT, module._BODY):
        for text in mapping.values():
            assert "{" not in text
            assert "}" not in text
            assert "%s" not in text


def test_the_two_languages_are_exactly_es_and_en() -> None:
    from app.guests.domain import notifications as module

    assert set(module._SUBJECT) == {"es", "en"}
    assert set(module._BODY) == {"es", "en"}


def test_the_subject_fits_the_column() -> None:
    """`notification_logs.subject` is `String(500)`."""
    for language in ("es", "en"):
        subject, _ = render_stored_guest_link_notice(language)
        assert len(subject) <= 500


def test_the_sent_email_contains_the_portal_url_verbatim() -> None:
    portal_url = "https://portal.autohost.ai/guest/abc123?token=xyz"

    for language in ("es", "en"):
        _, body = render_guest_link_delivery_email(language, portal_url)
        assert portal_url in body


def test_the_sent_email_languages_are_different_texts() -> None:
    portal_url = "https://portal.autohost.ai/guest/abc123?token=xyz"

    es_subject, es_body = render_guest_link_delivery_email("es", portal_url)
    en_subject, en_body = render_guest_link_delivery_email("en", portal_url)

    assert en_subject != es_subject
    assert en_body != es_body


def test_an_unrecognised_language_falls_back_to_spanish_for_the_sent_email() -> None:
    portal_url = "https://portal.autohost.ai/guest/abc123?token=xyz"

    for unrecognised in ("fr", "", "ES", "en-US", "not-a-language"):
        assert render_guest_link_delivery_email(
            unrecognised, portal_url
        ) == render_guest_link_delivery_email("es", portal_url)


def test_the_sent_email_does_not_collide_with_the_stored_notice() -> None:
    """The sent text must not leak into, or be identical to, the stored constant — they are
    different strings by construction, not by coincidence."""
    portal_url = "https://portal.autohost.ai/guest/abc123?token=xyz"

    for language in ("es", "en"):
        stored_subject, stored_body = render_stored_guest_link_notice(language)
        _, sent_body = render_guest_link_delivery_email(language, portal_url)

        assert sent_body != stored_body
        assert portal_url not in stored_body


def test_the_stored_notice_never_gains_an_interpolation_hole_from_the_sent_dict() -> None:
    """The stored function's own dicts (`_SUBJECT`/`_BODY`) stay untouched by the addition of
    `_SENT_BODY` — the sent dict is a separate mapping, not a mutation of the stored ones."""
    from app.guests.domain import notifications as module

    assert "portal_url" not in str(module._BODY)
    assert "{portal_url}" in module._SENT_BODY["es"]
    assert "{portal_url}" in module._SENT_BODY["en"]
