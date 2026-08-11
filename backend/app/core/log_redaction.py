"""Keeps route tokens out of the access log (`reservations-webhooks` rule 12(b);
`guest-portal-api` R1.2, D8).

**Two credentials travel in a URL path in this system, and both are covered here.** The
webhook route token came first and is what this module was written for; `guest-portal-api`
added `/api/v1/guest/{action}/{token}`, whose token is the *whole* credential — that surface
has no header secret behind it — so the leak this closes is strictly worse there. The filter
and its installer are named for the shape rather than for either caller because of that:
`PathTokenRedactingFilter`, not `WebhookTokenRedactingFilter`.

Deliberately one filter and not two. Two filters on the same logger doing the same job is how
one of them quietly stops being installed, and neither would know it.


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
#
# Case-insensitive: Starlette's routing IS case-sensitive, so `/API/v1/webhooks/…` never reaches
# the endpoint — but uvicorn logs it all the same, token included. The realistic trigger is a
# mis-cased URL pasted into a provider's panel, not an attacker (who already holds the token they
# would be leaking). Found by the security panel of section 2 on re-review.
_WEBHOOK_PATH = re.compile(r"(/api/v1/webhooks/[^/\s]+/)[^\s?]+", re.IGNORECASE)

# The guest portal, `/api/v1/guest/{action}/{token}` (`guest-portal-api` D8). The pattern
# matches the URL *shape*, so it covers the four routes of PRD §23 without naming any of them
# — which is the point of matching a shape and not a census: the fourth,
# `POST /guest/incident/{token}`, was mounted later and needed no change here.
# Same shape and same reasoning as the webhook one above: the token is the credential and it
# travels in the path, so uvicorn writes it on every request. Without this, anyone with read
# access to the log recovers every live stay — and unlike the webhook case there is no second
# factor behind it, because the guest surface has no header secret (D2).
#
# The **action** is kept, exactly as the provider is kept above: `info`, `checkin` or
# `incident` is not a secret and it is what an operator needs to read the log at all.
#
# Anchored on `/api/v1/guest/` plus one segment, so a **fifth** action added later is covered
# without touching this file — the residual risk the design's own Risks section names.
_GUEST_PORTAL_PATH = re.compile(r"(/api/v1/guest/[^/\s]+/)[^\s?]+", re.IGNORECASE)

REDACTED = "***"

_PREFIXES = ("/api/v1/webhooks/", "/api/v1/guest/")

_PATTERNS = (_WEBHOOK_PATH, _GUEST_PORTAL_PATH)


def redact_path_tokens(message: str) -> str:
    """The request line with any route token replaced. Pure, so it is testable on its own."""
    for pattern in _PATTERNS:
        message = pattern.sub(rf"\1{REDACTED}", message)
    return message


class PathTokenRedactingFilter(logging.Filter):
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
            if _mentions_token_path(args[2]):
                redacted = list(args)
                redacted[2] = redact_path_tokens(args[2])
                record.args = tuple(redacted)
            return True

        if isinstance(record.msg, str) and _mentions_token_path(record.msg):
            record.msg = redact_path_tokens(record.msg)
        return True


def _mentions_token_path(value: str) -> bool:
    """The cheap pre-check, and it has to agree with the regexes about case.

    A case-SENSITIVE `in` here would gate case-insensitive patterns, so a mis-cased path would
    never reach the substitution and the `re.IGNORECASE` above would be decoration.

    It also has to agree with them about **coverage**: every pattern needs its prefix listed,
    or that pattern silently never runs. That is why both live in module constants next to
    each other rather than being inlined — a second credential-bearing path was always coming,
    and `guest-portal-api` is it.
    """
    lowered = value.lower()
    return any(prefix in lowered for prefix in _PREFIXES)


def install_path_token_redaction() -> None:
    """Attach the filter to uvicorn's access logger, at most once.

    Called from `create_app()` rather than from a logging config file, because this project has
    no logging configuration to hang it on and adding one to carry a single filter would be a
    larger change than the leak it closes.

    Idempotent: `create_app()` runs once per process in production but many times across a test
    session, and a filter added on every call would be run once per copy on every log line.
    """
    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(existing, PathTokenRedactingFilter) for existing in access_logger.filters):
        return
    access_logger.addFilter(PathTokenRedactingFilter())
