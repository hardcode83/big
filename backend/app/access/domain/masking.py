"""The masked form of an access code (rule 4 of `sdd/steering/security.md`).

> "**Masked fields**: códigos de acceso siempre `****XX`"

Pure, and in `domain/` rather than next to the adapter, because the rule is a business
constraint and not a rendering detail: **the plaintext never leaves the request handler**.
`AccessRecordModel` has no column for it and none is added (design D9) — the operator types
the code, this derives the four-star form, and the original is discarded.

That is not a limitation of the MVP. PRD §15 is explicit that AutoHostAI does **not** control
the lock: GrinPass creates the code through the PMS and delivers it. What we record is that a
code exists (`MANUAL_ADDED`) and that the guest has it (`DELIVERED`).
"""

MASK = "****"
#: How many trailing characters survive. Rule 4 writes the shape as `****XX`.
VISIBLE_SUFFIX = 2


def mask_access_code(code: str) -> str:
    """`"481523"` → `"****23"`.

    Whitespace is stripped first: an operator pasting a code from a provider's panel brings
    a trailing newline often enough that the mask would otherwise end in it, and two codes
    that differ only in padding are the same code.

    **A code shorter than the visible suffix is masked whole**, never padded out to the
    canonical shape. `"7"` becomes `"****"`, not `"****7"`: revealing the entire secret is
    the one thing a mask may not do, and a short code is exactly where that would happen.
    """
    stripped = code.strip()
    if len(stripped) <= VISIBLE_SUFFIX:
        return MASK
    return f"{MASK}{stripped[-VISIBLE_SUFFIX:]}"


def looks_like(code: str, text: str) -> bool:
    """Whether `text` contains `code`, ignoring case and any separators.

    Used by `AccessRecord.register_manual_code` to refuse a code pasted into the free-text
    `notes` of the same request. A raw `code in notes` was the first version and the security
    panel got past it twice: `code="AbC123"` with `notes="el código es abc123"`, and a code
    split by a space (`"481 523"`). Both stored the plaintext in the one request whose whole
    purpose is not to.

    Normalising both sides to lowercase alphanumerics closes both, because the separators an
    operator types — spaces, dashes, dots — vanish from the comparison.

    **It errs towards refusing**, and that is the intended direction: a short code can collide
    with an ordinary number in the notes ("piso 12"), which costs the operator a `422` and a
    reword. The opposite mistake stores a door code in a column served to the whole tenant.
    Recoverable versus not.
    """
    normalised_code = _comparable(code)
    return bool(normalised_code) and normalised_code in _comparable(text)


def _comparable(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())
