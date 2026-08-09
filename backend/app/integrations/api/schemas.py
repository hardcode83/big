"""Request and response DTOs for the integration endpoints (R4.1, R2.3, PRD §23)."""

import uuid

from pydantic import BaseModel, Field

from app.integrations.application.ingest import IngestReport
from app.integrations.application.use_cases import WebhookEndpointMaterial
from app.integrations.domain.enums import PMSProvider

WEBHOOK_RECEIVER_PREFIX = "/api/v1/webhooks"
"""Where the receiving route of design D1 lives, as the operator has to type it.

Written out rather than composed from `app.main.API_V1_PREFIX`, which is where the prefix is
defined: `main` imports this router, so importing it back would be a cycle. The duplication is
the price, and it is paid once — `api/webhooks_router.py` (task 2.5) mounts at this constant and
`tests/integrations/test_webhook_endpoints_api.py` asserts that the URL handed to the operator
is a route this app actually serves, so a divergence fails rather than ships.
"""

# The provider's header name, not ours: it is whatever the provider's panel sends. Constrained to
# the alphabet every real one uses instead of the full RFC 7230 token set, because the value ends
# up in a header lookup and a name containing a colon, a space or a newline can only be a mistake
# or an attempt at something.
_HEADER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$"


class CreateWebhookEndpointRequest(BaseModel):
    """What `POST /api/v1/integrations/webhook-endpoints` accepts (R2.1).

    Neither secret appears here, and that is the whole shape of the operation: the caller does
    not choose the material, the system mints it. A request that accepted a token would let an
    operator paste a value they had already used somewhere, which is exactly the "constante
    global" rule 12(a) forbids.
    """

    provider: PMSProvider
    header_name: str = Field(pattern=_HEADER_NAME_PATTERN)


class WebhookEndpointMaterialResponse(BaseModel):
    """The one and only time either secret is serialised (R2.3, rule 3(a)'s narrow exception).

    There is deliberately **no read endpoint** returning this shape, not even with the values
    masked: rule 3(a) permits handing them over "una sola vez en el momento de generarlo y en
    cada rotación", and a masked read would be a second serialisation the exception does not
    cover. Losing the URL is repaired by rotating, which is why `notice` says so in the response
    instead of in documentation the operator will not have open.
    """

    id: uuid.UUID
    provider: PMSProvider
    header_name: str
    webhook_url: str
    header_secret: str
    notice: str = (
        "Copy the URL and the header secret into the provider's panel now: they are shown "
        "once and cannot be retrieved afterwards. If they are lost, rotate this endpoint."
    )

    @classmethod
    def of(
        cls, material: WebhookEndpointMaterial, *, base_url: str
    ) -> "WebhookEndpointMaterialResponse":
        """`base_url` is the origin the operator is already talking to, so it is the right one.

        Taken from the request rather than from configuration: this API has no public-origin
        setting, and inventing one would be a third knob for a fact the request already carries
        (the same argument design D5 makes against `WEBHOOK_MAX_BODY_BYTES`). It is not a Host
        header injection either — the header belongs to the authenticated operator's own request,
        so the origin reflected back is the one they used.
        """
        provider = material.provider.value.lower()
        return cls(
            id=material.endpoint_id,
            provider=material.provider,
            header_name=material.header_name,
            webhook_url=(
                f"{base_url.rstrip('/')}{WEBHOOK_RECEIVER_PREFIX}/"
                f"{provider}/{material.webhook_token}"
            ),
            header_secret=material.header_secret,
        )


class RowErrorResponse(BaseModel):
    """One row the import could not take, with what a person needs to fix it."""

    line: int | None = None
    reference: str | None = None
    reason: str


class ImportReportResponse(BaseModel):
    """What the import did, per outcome (R4.1, R4.2).

    `created` and `updated` are separate because that difference is the observable proof of
    idempotency: importing the same file twice must show `created: 0` the second time.
    """

    created: int
    updated: int
    skipped: int
    errors: list[RowErrorResponse]

    @classmethod
    def from_report(cls, report: IngestReport) -> "ImportReportResponse":
        """Every error already carries its line when the source had one (R4.2).

        The use case merges the rows the parser rejected with the rows the ingest rejected, so
        this is a straight mapping — earlier it stitched the two lists together here, which is
        how the ingest-level errors ended up without a line number.
        """
        return cls(
            created=report.created,
            updated=report.updated,
            skipped=report.skipped,
            errors=[
                RowErrorResponse(line=error.line, reference=error.reference, reason=error.reason)
                for error in report.errors
            ],
        )
