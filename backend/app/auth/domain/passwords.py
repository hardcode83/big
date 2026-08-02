"""Temporary passwords for accounts an administrator creates (R1.2, R4.1, design D9/D20).

Pure domain: `secrets` is the standard library, so `domain/` stays free of the imports
`tests/test_layering.py` forbids. No port and no adapter — there is no external system and
no second implementation to substitute, and a port here would be ceremony
(`steering/backend-architecture.md` §"Cuándo simplificar").

The alphabet has no ambiguous glyphs. That is not cosmetic: this string gets dictated or
pasted from one person to another, and `0`/`O` or `1`/`l`/`I` turn a working credential into
a support conversation.
"""

import secrets
import string

# 16 characters over this 57-glyph alphabet is ~93 bits — far past anything that matters for
# a credential meant to be rotated on first use, and comfortably under bcrypt's 72-BYTE input
# limit, which `auth-tenancy` refuses to truncate silently (its R1.3). ASCII only, so 16
# characters are 16 bytes.
TEMPORARY_PASSWORD_LENGTH = 16

DIGITS = "23456789"  # no 0, no 1
UPPERCASE = "".join(c for c in string.ascii_uppercase if c not in "IO")
LOWERCASE = "".join(c for c in string.ascii_lowercase if c not in "l")
ALPHABET = DIGITS + UPPERCASE + LOWERCASE

_CLASSES = (DIGITS, UPPERCASE, LOWERCASE)
# A bound rather than `while True`: the probability of needing even ten attempts is
# negligible, so a cap can only be reached if someone breaks the alphabet — and then a loud
# failure beats a process spinning for ever.
_MAX_ATTEMPTS = 100


def generate_temporary_password() -> str:
    """A fresh temporary password. Never logged, never stored in cleartext.

    Guarantees at least one glyph of each class. Not because any policy demands it today —
    there is none — but because `auth-account-recovery` is expected to add one, and a
    generator that can emit sixteen digits would then be producing passwords its own system
    rejects.
    """
    for _ in range(_MAX_ATTEMPTS):
        candidate = "".join(secrets.choice(ALPHABET) for _ in range(TEMPORARY_PASSWORD_LENGTH))
        if all(any(glyph in klass for glyph in candidate) for klass in _CLASSES):
            return candidate
    raise RuntimeError(
        "Could not generate a temporary password meeting its own character classes; "
        "the alphabet or the length must have been changed inconsistently."
    )
