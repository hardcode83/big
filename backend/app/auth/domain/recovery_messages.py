"""The two texts of a recovery notice: the one sent, and the one stored (R4.2, design D2).

They are **deliberately different texts produced by different code paths**, and that is the
whole point of this module. Rule 11 of `steering/security.md` grants
`notification_logs.subject`/`body` exactly one exception — the masked `****XX` form of an
access code — and a live recovery link is not that. So the link goes to the adapter inside
the request, and the row records *that a notice was sent*, not what it said.

Keeping the two apart in one small module, rather than as an argument that may or may not be
passed, is what makes the guarantee structural: there is no call that renders the stored body
*with* a link, because the stored body takes no argument at all.

English, like every other system-generated message in the backend (`steering/backend.md`).
"""

RECOVERY_EMAIL_SUBJECT = "Reset your AutoHostAI password"

# What is stored. No link, no token, no argument that could carry one (R4.2).
STORED_RECOVERY_SUBJECT = "Password reset requested"
STORED_RECOVERY_BODY = (
    "A password reset link was sent to this account. "
    "The link itself is not recorded: it is a single-use credential."
)


def render_recovery_email(link: str) -> tuple[str, str]:
    """The subject and body actually handed to the email adapter.

    The return value lives for the length of one request and is never persisted — the row
    written afterwards uses the `STORED_*` constants above.
    """
    body = (
        "Someone asked to reset the password of this AutoHostAI account.\n\n"
        f"Open this link to choose a new one:\n{link}\n\n"
        "If it was not you, no action is needed: the link expires on its own and "
        "your current password still works."
    )
    return RECOVERY_EMAIL_SUBJECT, body
