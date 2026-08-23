"""`GET /api/v1/incident-photos/{photo_id}` — the anonymous signed serving route (R4).

**The route's body does not live here.** It is
`app/integrations/api/signed_media.py::build_signed_media_router`, shared with `cleaning` since
design D5, and everything that makes this surface safe is documented at that home: the constant
`403` body, the `nosniff` stamp on every answer, the `Cache-Control` derived from what is left of
the signature, and the resolve → verify → serve ordering that is the endpoint's entire
authorisation. Read that module before editing anything that reaches this route.

What lives here is this module's whole remaining job: naming the prefix, the tag, the operation
and the log event `maintenance` publishes, and which use case builder resolves its photos.

**It is a router of its own, and R4.6 says so explicitly**: it must not hang off
`incidents_router`, whose every path carries a `require(...)`. An anonymous endpoint sharing a
router with fourteen authorised ones is one copied decorator away from either claiming a `401`
it cannot return or, far worse, from an authorised sibling inheriting nothing.

The path parameter is `photo_id` rather than something generic because that name is part of the
published contract, and because R4.6/design D12 name the census entry as
`("GET", "/api/v1/incident-photos/{photo_id}")`.
"""

from app.integrations.api.signed_media import build_signed_media_router
from app.maintenance.api.dependencies import get_serve_incident_photo_use_case

router = build_signed_media_router(
    prefix="/incident-photos",
    tag="maintenance",
    operation_name="serve_incident_photo",
    summary="Serve an incident photo by signed URL",
    description=(
        "**Anonymous by design** (`steering/security.md` rule 5): photos travel as signed "
        "URLs, and a browser fetching an `<img src>` sends no `Authorization` header. The "
        "`exp` and `sig` query parameters are the credential — `sig` is an HMAC over the "
        "object's internal key and `exp`, so it cannot be moved to another photo, another "
        "tenant or a later deadline.\n\n"
        "Only tenants whose `storage_type` is `LOCAL` are served here; an `S3` tenant's URLs "
        "point straight at the object store and this route answers `404` for them."
    ),
    log_event="maintenance",
    use_case_dep=get_serve_incident_photo_use_case,
)
