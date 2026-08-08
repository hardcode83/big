"""Keeps the webhook route token out of the access log (`reservations-webhooks`, rule 12(b)).

**The problem is structural, not a slip.** Design D1 puts the token in the URL *path*, which is
what makes the route non-guessable per tenant — and a path is the one part of a request that every
web server, proxy and log aggregator records by default. uvicorn's access log is on unless
`--no-access-log` is passed, so without this every delivery wrote a line like

    POST /api/v1/webhooks/BEDS24/<the tenant's live route token> HTTP/1.1" 202

for every tenant, on every request. `RedisWebhookThrottle` is careful to key on the *hash* so the
token never becomes a Redis key; the access log undid that in a place with far more readers.

Rule 12 says (a) and (b) "se sostienen mutuamente — si el secreto se filtra queda la ruta, y si la
ruta se adivina queda el secreto". Anyone with log-read access recovering half the pair for every
tenant is exactly the situation that pairing exists to prevent. Found by the security panel of
section 2.

**Redaction rather than moving the token out of the path**: moving it to a header would take rule
12(b)'s non-guessable-route property with it, which is the more expensive loss. Disabling the
access log wholesale would blind operations on every other endpoint.
"""

import logging
import re

# Matches the token segment of `/api/v1/webhooks/{provider}/{token}` wherever it appears in the
# formatted request line. Anchored on the literal prefix so it cannot touch any other path, and
# the provider is kept: it is not a secret and it is what an operator needs in order to tell which
# integration is delivering.
_WEBHOOK_PATH = re.compile(r"(/api/v1/webhooks/[^/\s]+/)[^\s?]+")

REDACTED = "***"


def redact_webhook_token(message: str) -> str:
    """The request line with the route token replaced. Pure, so it is testable on its own."""
    return _WEBHOOK_PATH.sub(rf"\1{REDACTED}", message)


class WebhookTokenRedactingFilter(logging.Filter):
    """Rewrites the path argument of a uvicorn access record before it is formatted.

    Operates on `record.args`, not on the final string, because that is where uvicorn keeps the
    path: its access formatter is called with a tuple of
    `(client_addr, method, full_path, http_version, status_code)`. Editing the argument leaves the
    format string and every other field untouched.

    Falls back to rewriting `record.msg` when the shape is anything else — a different uvicorn
    version, or another logger routed through this filter. **Fails safe by construction**: every
    branch returns `True`, so a record this filter does not understand is still emitted rather
    than swallowed. A logging filter that dropped lines on an unexpected shape would trade a
    credential leak for silent loss of the access log, which is not a trade worth making.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            if "/api/v1/webhooks/" in args[2]:
                redacted = list(args)
                redacted[2] = redact_webhook_token(args[2])
                record.args = tuple(redacted)
            return True

        if isinstance(record.msg, str) and "/api/v1/webhooks/" in record.msg:
            record.msg = redact_webhook_token(record.msg)
        return True


def install_webhook_token_redaction() -> None:
    """Attach the filter to uvicorn's access logger, at most once.

    Called from `create_app()` rather than from a logging config file, because this project has
    no logging configuration to hang it on and adding one to carry a single filter would be a
    larger change than the leak it closes.

    Idempotent: `create_app()` runs once per process in production but many times across a test
    session, and a filter added on every call would be run once per copy on every log line.
    """
    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, WebhookTokenRedactingFilter) for existing in access_logger.filters):
        return
    access_logger.addFilter(WebhookTokenRedactingFilter())
