"""The webhook route token never reaches the access log (rule 12(b), `reservations-webhooks`).

Found by the security panel of section 2, and worth its own file because the leak is not in any
handler: the token is a path segment by design (D1), and uvicorn logs paths. The careful hashing
in `RedisWebhookThrottle` keeps it out of Redis; nothing kept it out of the log, which has more
readers.
"""

import logging

import pytest

from app.core.log_redaction import (
    REDACTED,
    WebhookTokenRedactingFilter,
    install_webhook_token_redaction,
    redact_webhook_token,
)
from app.main import create_app

TOKEN = "sZ9_kQ2mR7tYw1xV-live-route-token"
REQUEST_LINE = f"/api/v1/webhooks/BEDS24/{TOKEN}"


def test_the_token_is_replaced_and_the_provider_kept() -> None:
    """The provider is not a secret and an operator needs it to tell integrations apart."""
    redacted = redact_webhook_token(REQUEST_LINE)

    assert TOKEN not in redacted
    assert redacted == f"/api/v1/webhooks/BEDS24/{REDACTED}"


def test_a_query_string_does_not_smuggle_the_token_through() -> None:
    redacted = redact_webhook_token(f"{REQUEST_LINE}?retry=2")

    assert TOKEN not in redacted


def test_other_paths_are_untouched() -> None:
    """A redactor that mangles unrelated paths gets disabled, which is the same as absent."""
    for path in (
        "/api/v1/integrations/webhook-endpoints",
        "/api/v1/reservations/8f14e45f",
        "/health",
    ):
        assert redact_webhook_token(path) == path


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

    assert WebhookTokenRedactingFilter().filter(record) is True
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

    assert WebhookTokenRedactingFilter().filter(record) is True
    assert TOKEN not in record.getMessage()


def test_installing_twice_adds_one_filter() -> None:
    """`create_app()` runs once per process but many times per test session."""
    install_webhook_token_redaction()
    install_webhook_token_redaction()

    installed = [
        filter_
        for filter_ in logging.getLogger("uvicorn.access").filters
        if isinstance(filter_, WebhookTokenRedactingFilter)
    ]
    assert len(installed) == 1


def test_creating_the_app_installs_the_filter() -> None:
    """The wiring, not just the mechanism — the same gap the body-ceiling tests exist to close."""
    logging.getLogger("uvicorn.access").filters = [
        filter_
        for filter_ in logging.getLogger("uvicorn.access").filters
        if not isinstance(filter_, WebhookTokenRedactingFilter)
    ]

    create_app()

    assert any(
        isinstance(filter_, WebhookTokenRedactingFilter)
        for filter_ in logging.getLogger("uvicorn.access").filters
    )


@pytest.mark.parametrize("provider", ["BEDS24", "beds24", "channex"])
def test_every_provider_spelling_is_covered(provider: str) -> None:
    """The route accepts the provider in any case, so the redactor cannot key on one spelling."""
    assert TOKEN not in redact_webhook_token(f"/api/v1/webhooks/{provider}/{TOKEN}")
