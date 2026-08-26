"""`GET /api/v1/cleaning-photos/{photo_id}` — the anonymous signed serving route.

**The route's body no longer lives here.** `incident-photos` (design D5) extracted it to
`app/integrations/api/signed_media.py`, because `maintenance` needed the same route over its own
table and two copies of that security argument are two places it can diverge. What is left here
is this module's whole remaining job: naming which prefix, tag, operation and log event
`cleaning` publishes, and which use case builder resolves its photos.

Everything the extraction moved — the constant `403` body, the `nosniff` stamp on every answer,
the `Cache-Control` derived from what is left of the signature, and the resolve → verify → serve
ordering that is the endpoint's entire authorisation — is documented at its new home. Read
`app/integrations/api/signed_media.py` before editing anything that reaches this route.

**The published contract did not move with it.** `operation_name` is `serve_cleaning_photo`
because FastAPI derives `operationId` from the route's name, and
`serve_cleaning_photo_api_v1_cleaning_photos__photo_id__get` is in `backend/openapi.json` and in
the frontend artefact generated from it. The summary and description below are the ones that
were published too, byte for byte.
"""

from app.cleaning.api.dependencies import get_serve_cleaning_photo_use_case
from app.integrations.api.signed_media import build_signed_media_router

router = build_signed_media_router(
    prefix="/cleaning-photos",
    tag="cleaning",
    operation_name="serve_cleaning_photo",
    summary="Serve a cleaning photo by signed URL",
    description=(
        "**Anonymous by design** (`steering/security.md` rule 5): photos travel as signed "
        "URLs, and a browser fetching an `<img src>` sends no `Authorization` header. The "
        "`exp` and `sig` query parameters are the credential — `sig` is an HMAC over the "
        "object's internal key and `exp`, so it cannot be moved to another photo, another "
        "tenant or a later deadline.\n\n"
        "Only tenants whose `storage_type` is `LOCAL` are served here; an `S3` tenant's URLs "
        "point straight at the object store and this route answers `404` for them."
    ),
    log_event="cleaning",
    use_case_dep=get_serve_cleaning_photo_use_case,
)
