"""No route token reaches the access log (rule 12(b), `reservations-webhooks`;
R1.2 and D8 of `guest-portal-api`).

Found by the security panel of `reservations-webhooks` section 2, and worth its own file
because the leak is not in any handler: the token is a path segment by design, and uvicorn
logs paths. The careful hashing in `RedisWebhookThrottle` keeps it out of Redis; nothing kept
it out of the log, which has more readers.

`guest-portal-api` added the second path-borne credential and generalised the filter. Its
token is worse to lose than the webhook one: the webhook route has a header secret behind it
(rule 12(a)), and the guest portal has nothing — the token in the path *is* the credential.
"""

import logging

import pytest

from app.core.log_redaction import (
    REDACTED,
    PathTokenRedactingFilter,
    install_path_token_redaction,
    redact_path_tokens,
)
from app.main import create_app

TOKEN = "sZ9_kQ2mR7tYw1xV-live-route-token"
REQUEST_LINE = f"/api/v1/webhooks/BEDS24/{TOKEN}"


def test_the_token_is_replaced_and_the_provider_kept() -> None:
    """The provider is not a secret and an operator needs it to tell integrations apart."""
    redacted = redact_path_tokens(REQUEST_LINE)

    assert TOKEN not in redacted
    assert redacted == f"/api/v1/webhooks/BEDS24/{REDACTED}"


def test_a_query_string_does_not_smuggle_the_token_through() -> None:
    redacted = redact_path_tokens(f"{REQUEST_LINE}?retry=2")

    assert TOKEN not in redacted


def test_other_paths_are_untouched() -> None:
    """A redactor that mangles unrelated paths gets disabled, which is the same as absent."""
    for path in (
        "/api/v1/integrations/webhook-endpoints",
        "/api/v1/reservations/8f14e45f",
        "/health",
    ):
        assert redact_path_tokens(path) == path


# --- The guest portal's routes (`guest-portal-api` R1.2, D8) --------------------------

GUEST_TOKEN = "Kp3_vB8nQ1sTz6yW-live-guest-token"


@pytest.mark.parametrize("action", ["info", "checkin", "incident", "messages"])
def test_a_guest_portal_token_is_replaced_and_the_action_kept(action: str) -> None:
    """Every portal route shares one shape, so one pattern covers them all.

    Parametrized over the actions rather than counted: this docstring said "all four routes"
    while the parametrize listed three, and `guest-portal-messaging` then added `messages` —
    so the number described neither the surface nor the list below it.

    The action is kept for the same reason the provider is kept above: it is not a secret,
    and without it the log says only that *somebody* used the portal.
    """
    redacted = redact_path_tokens(f"/api/v1/guest/{action}/{GUEST_TOKEN}")

    assert GUEST_TOKEN not in redacted
    assert redacted == f"/api/v1/guest/{action}/{REDACTED}"


def test_an_unwritten_guest_action_is_covered_without_touching_the_pattern() -> None:
    """The residual risk the design's own Risks section names, closed by anchoring.

    "El riesgo real es que alguien añada una quinta ruta de huésped con otra forma de path y
    el patrón no la cubra." The pattern anchors on `/api/v1/guest/` plus one segment rather
    than on the actions that happen to exist, so a route nobody has written yet is already
    redacted. A pattern enumerating `info|checkin|incident` would have passed every other test
    in this file and leaked the day a new action landed.

    **That day came**: `guest-portal-messaging` added `/api/v1/guest/messages/{token}`, and
    this file needed no change to the pattern — only the parametrize above gained the action,
    and it gained it to be covered explicitly rather than because it had been leaking. The test
    was named `..._a_fifth_guest_action_...` when a fifth was hypothetical; it is renamed
    because the hypothetical is now history and the point is the anchoring, not the ordinal.
    """
    redacted = redact_path_tokens(f"/api/v1/guest/receipt/{GUEST_TOKEN}")

    assert GUEST_TOKEN not in redacted
    assert redacted == f"/api/v1/guest/receipt/{REDACTED}"


def test_a_mis_cased_guest_path_is_still_redacted() -> None:
    """Starlette's routing is case-sensitive, so `/API/v1/guest/…` never reaches a handler —
    and uvicorn logs it anyway, token included. The realistic trigger is a mis-cased link,
    not an attacker; the same reasoning the webhook pattern already carries."""
    redacted = redact_path_tokens(f"/API/V1/GUEST/Info/{GUEST_TOKEN}")

    assert GUEST_TOKEN not in redacted


def test_a_query_string_does_not_smuggle_a_guest_token_through() -> None:
    redacted = redact_path_tokens(f"/api/v1/guest/checkin/{GUEST_TOKEN}?lang=es")

    assert GUEST_TOKEN not in redacted


def test_both_credentials_are_redacted_in_one_line() -> None:
    """One filter, two patterns — so neither can be the one that stops being installed.

    Contrived as a request line, and deliberate as a regression test: the filter applies
    every pattern rather than returning after the first match, and a `return` slipped into
    that loop would leave whichever credential came second in the clear.
    """
    line = f"/api/v1/webhooks/BEDS24/{TOKEN} /api/v1/guest/info/{GUEST_TOKEN}"

    redacted = redact_path_tokens(line)

    assert TOKEN not in redacted
    assert GUEST_TOKEN not in redacted


def test_the_guest_prefix_is_declared_for_the_cheap_precheck() -> None:
    """The pre-check gates the regexes, so a pattern whose prefix is missing never runs.

    Asserted directly because that failure is silent: the pattern would be present, correct,
    and dead. Pinned via the filter rather than the pure function, since the pre-check is
    what the filter consults.
    """
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("1.2.3.4:5", "GET", f"/api/v1/guest/info/{GUEST_TOKEN}", "1.1", 200),
        exc_info=None,
    )

    assert PathTokenRedactingFilter().filter(record) is True
    assert GUEST_TOKEN not in str(record.args)


def test_the_filter_rewrites_the_access_record_argument() -> None:
    """uvicorn keeps the path in `record.args[2]`, so that is what has to change."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "POST", REQUEST_LINE, "1.1", 202),
        exc_info=None,
    )

    assert PathTokenRedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()
    assert REDACTED in record.getMessage()


def test_a_record_of_an_unexpected_shape_is_still_emitted() -> None:
    """Fails safe: a filter that dropped lines it did not understand would trade a credential
    leak for silent loss of the access log."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"something unexpected about {REQUEST_LINE}",
        args=None,
        exc_info=None,
    )

    assert PathTokenRedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()


def test_installing_twice_adds_one_filter() -> None:
    """`create_app()` runs once per process but many times per test session."""
    install_path_token_redaction()
    install_path_token_redaction()

    installed = [
        filter_
        for filter_ in logging.getLogger("uvicorn.access").filters
        if isinstance(filter_, PathTokenRedactingFilter)
    ]
    assert len(installed) == 1


def test_creating_the_app_installs_the_filter() -> None:
    """The wiring, not just the mechanism — the same gap the body-ceiling tests exist to close."""
    logging.getLogger("uvicorn.access").filters = [
        filter_
        for filter_ in logging.getLogger("uvicorn.access").filters
        if not isinstance(filter_, PathTokenRedactingFilter)
    ]

    create_app()

    assert any(
        isinstance(filter_, PathTokenRedactingFilter)
        for filter_ in logging.getLogger("uvicorn.access").filters
    )


@pytest.mark.parametrize("provider", ["BEDS24", "beds24", "channex"])
def test_every_provider_spelling_is_covered(provider: str) -> None:
    """The route accepts the provider in any case, so the redactor cannot key on one spelling."""
    assert TOKEN not in redact_path_tokens(f"/api/v1/webhooks/{provider}/{TOKEN}")


@pytest.mark.parametrize("prefix", ["/API/v1/webhooks", "/Api/V1/Webhooks", "/api/V1/webhooks"])
def test_a_miscased_prefix_is_redacted_too(prefix: str) -> None:
    """Starlette's routing is case-sensitive, so such a request 404s — and is logged anyway.

    The realistic trigger is a mis-cased URL pasted into a provider's panel. Both the regex and the
    cheap `in` pre-check have to agree about case, or the pre-check silently gates the pattern.
    """
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "POST", f"{prefix}/BEDS24/{TOKEN}", "1.1", 404),
        exc_info=None,
    )

    assert PathTokenRedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()
