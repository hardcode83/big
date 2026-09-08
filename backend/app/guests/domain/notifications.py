"""The two texts of a guest-portal-link delivery notice: the one sent, and the one stored
(`guest-link-delivery` R3.1/R3.4, design D6).

They are **deliberately different texts produced by different functions**, mirroring
`render_recovery_email` / `STORED_RECOVERY_*` in `auth/domain/recovery_messages.py`. Rule 11 of
`steering/security.md` gives `notification_logs.subject`/`body` exactly one exception for the
whole codebase — the masked `****XX` form of an access code — and a live portal URL is not it.
So the row records *that a notice was sent*, not what it said: `render_stored_guest_link_notice`
below returns fixed prose with no guest name, no reservation id, no property name, and above all
no portal URL or token. Whatever identifies *which* stay the row is about travels on the
`NotificationLog` itself, via `related_type`/`related_id` (`"reservation"` / the reservation's
id) — never inside the rendered text.

But R3.1 requires the guest to actually receive a usable link, and rule 11 forbids that link from
ever reaching the persisted row — so a second function, `render_guest_link_delivery_email`, builds
the *sent* text: it takes the real portal URL and hands the adapter a string the stored function
could never produce. That return value lives for the length of one request and is never
persisted; the row written afterwards uses the stored function's constants instead.

Both functions are keyed by `Guest.preferred_language` (design D6): `es` first because that is
what the field defaults to, `en` second, and any other value falls back to `es` rather than
raising — the same shrug `Locale.resolve` gives an unrecognised `preferred_language`, because a
send must not fail over a language it does not recognise.
"""

_SUBJECT = {
    "es": "Su enlace de acceso al portal de huéspedes",
    "en": "Your guest portal access link",
}

_BODY = {
    "es": (
        "Le hemos enviado un enlace de acceso al portal de huéspedes para su reserva. "
        "Utilícelo para consultar la información de su estancia."
    ),
    "en": (
        "We have sent you an access link to the guest portal for your reservation. "
        "Use it to view your stay information."
    ),
}

# The sent text's body, keyed by language, with the one hole the stored text is forbidden from
# having: the real portal URL (R3.1). Subject stays the same `_SUBJECT` used for the stored
# notice — only the body needs to carry the link.
_SENT_BODY = {
    "es": (
        "Le hemos enviado su enlace de acceso al portal de huéspedes para su reserva. "
        "Puede acceder aquí: {portal_url}"
    ),
    "en": (
        "Here is your access link to the guest portal for your reservation: {portal_url}"
    ),
}


def render_stored_guest_link_notice(language: str) -> tuple[str, str]:
    """The constant `(subject, body)` pair persisted to `notification_logs` (R3.4).

    `language` is `GuestSummary.preferred_language` as it already exists (design D6) — no new
    resolver, no classification of guest-authored text (there is none to classify at send
    time). Any value other than `"es"`/`"en"` falls back to `"es"`, the field's own default,
    rather than raising: a send must not fail because of a language this catalogue does not
    recognise.

    Fixed prose only — no `{...}`, no `%s`, no f-string hole for a guest name, a reservation
    id or the link itself (R3.4). There is nothing this function could be handed that would
    end up in the returned strings, because it takes nothing but the language.
    """
    key = language if language in _SUBJECT else "es"
    return _SUBJECT[key], _BODY[key]


def render_guest_link_delivery_email(language: str, portal_url: str) -> tuple[str, str]:
    """The subject and body actually handed to the EMAIL adapter — contains the real link.

    Mirrors `render_recovery_email` (`auth/domain/recovery_messages.py`): this return value
    lives for the length of one request and is never persisted. The row written afterwards
    uses the link-free constants above, via `render_stored_guest_link_notice` (R3.4) — this
    function exists so the guest can actually reach the portal (R3.1), which the persisted row
    is forbidden from carrying (rule 11 of `steering/security.md`).
    """
    key = language if language in _SUBJECT else "es"
    return _SUBJECT[key], _SENT_BODY[key].format(portal_url=portal_url)
