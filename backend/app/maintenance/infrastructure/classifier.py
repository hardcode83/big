"""The development adapter of `IncidentClassifier` (R1.1, design D1, D4).

Deterministic and offline: the same text always yields the same verdict, which is what lets
the job of D2 stop retrying an incident it has already looked at (D3) and what makes the
tests of this module assertions rather than approximations.

**It lives here and not in `app/integrations/`** because it talks to no external system and
is shared with nobody; `steering/backend.md` reserves that package for *"adapters externos
compartidos"*. A real provider implements the same port and goes there.

**The `summary` never quotes the input**, which is the contract D4 fixes and this adapter
satisfies by construction: every summary is a constant of `_SUMMARIES` chosen by category,
so no path exists from `title`/`description` to `incidents.ai_summary`. That is a security
property and not a stylistic one — the column is a rule-11 sink of `steering/security.md`
under the structured form by default, its writer is ours, and its input is prose an
anonymous guest typed.
"""

import re
import unicodedata
from decimal import Decimal

from app.maintenance.domain.enums import IncidentCategory, IncidentSeverity
from app.maintenance.domain.value_objects import IncidentClassification

#: What the adapter calls itself in `ai_classification["adapter"]`. An identifier, which is
#: the closed form `Incident.classify` accepts.
ADAPTER_NAME = "RuleBasedIncidentClassifier"

#: Keywords per category, in the two languages the product serves (`sdd/project.md`: UI in
#: ES/EN). A tuple of pairs and not a dict literal because **the order is the tie-break**:
#: a text that matches two categories equally well is resolved by this order, and a `dict`
#: would hide that behind insertion semantics nobody reading would think to check.
#:
#: Ordered most specific first. `SAFETY` leads because a text mentioning both smoke and a
#: broken appliance is a safety incident that happens to involve an appliance.
_KEYWORDS: tuple[tuple[IncidentCategory, tuple[str, ...]], ...] = (
    (
        IncidentCategory.SAFETY,
        ("fuego", "incendio", "humo", "gas", "fire", "smoke", "alarm", "alarma"),
    ),
    (
        IncidentCategory.LOCK,
        ("cerradura", "cerrojo", "llave", "lock", "key"),
    ),
    # `keypad` is here and not with `LOCK`: a keypad problem is about getting in, and the
    # remedy is a code rather than a locksmith. `LOCK` leads on the tie-break, so leaving it
    # there would have swallowed every "the keypad will not take my code".
    (
        IncidentCategory.ACCESS,
        ("acceso", "codigo", "portal", "access", "code", "entry", "door", "keypad"),
    ),
    (
        IncidentCategory.WATER,
        ("agua", "fuga", "gotea", "inundacion", "water", "leak", "flood"),
    ),
    (
        IncidentCategory.PLUMBING,
        ("wc", "inodoro", "desague", "atasco", "tuberia", "toilet", "drain", "sink"),
    ),
    (
        IncidentCategory.ELECTRICITY,
        ("luz", "enchufe", "electricidad", "diferencial", "power", "socket", "light"),
    ),
    (
        IncidentCategory.HVAC,
        ("calefaccion", "aire", "climatizacion", "caldera", "heating", "boiler", "ac"),
    ),
    (
        IncidentCategory.APPLIANCE,
        ("nevera", "lavadora", "horno", "microondas", "fridge", "oven", "washer"),
    ),
    (
        IncidentCategory.WIFI,
        ("wifi", "internet", "router", "conexion", "connection"),
    ),
    (
        IncidentCategory.NOISE,
        ("ruido", "vecinos", "fiesta", "noise", "neighbours", "party"),
    ),
    (
        IncidentCategory.CLEANING,
        ("sucio", "limpieza", "basura", "dirty", "cleaning", "rubbish"),
    ),
    (
        IncidentCategory.DAMAGE,
        ("roto", "rota", "grieta", "rotura", "broken", "cracked", "damaged"),
    ),
)

#: Severity per category. Named here and not derived from the keyword that matched, so the
#: verdict a manager sees is a property of *what* broke and not of which synonym the guest
#: happened to use.
_SEVERITIES: dict[IncidentCategory, IncidentSeverity] = {
    IncidentCategory.SAFETY: IncidentSeverity.CRITICAL,
    IncidentCategory.LOCK: IncidentSeverity.HIGH,
    IncidentCategory.ACCESS: IncidentSeverity.HIGH,
    IncidentCategory.WATER: IncidentSeverity.HIGH,
    IncidentCategory.ELECTRICITY: IncidentSeverity.HIGH,
    IncidentCategory.PLUMBING: IncidentSeverity.MEDIUM,
    IncidentCategory.HVAC: IncidentSeverity.MEDIUM,
    IncidentCategory.APPLIANCE: IncidentSeverity.MEDIUM,
    IncidentCategory.DAMAGE: IncidentSeverity.MEDIUM,
    IncidentCategory.WIFI: IncidentSeverity.LOW,
    IncidentCategory.NOISE: IncidentSeverity.LOW,
    IncidentCategory.CLEANING: IncidentSeverity.LOW,
    IncidentCategory.OTHER: IncidentSeverity.MEDIUM,
}

#: The closed vocabulary of D4: one constant per category, and the **only** thing that ever
#: reaches `incidents.ai_summary` from this adapter. Adding a category to `IncidentCategory`
#: without adding its line here fails in `_summary_for`, loudly, rather than falling back to
#: something derived from the guest's words.
_SUMMARIES: dict[IncidentCategory, str] = {
    IncidentCategory.SAFETY: "Possible safety hazard reported at the property",
    IncidentCategory.LOCK: "Lock or key problem reported at the property",
    IncidentCategory.ACCESS: "Access problem reported at the property",
    IncidentCategory.WATER: "Water leak or supply problem reported at the property",
    IncidentCategory.PLUMBING: "Plumbing problem reported at the property",
    IncidentCategory.ELECTRICITY: "Electrical problem reported at the property",
    IncidentCategory.HVAC: "Heating or air conditioning problem reported at the property",
    IncidentCategory.APPLIANCE: "Appliance problem reported at the property",
    IncidentCategory.WIFI: "Internet connectivity problem reported at the property",
    IncidentCategory.NOISE: "Noise problem reported at the property",
    IncidentCategory.CLEANING: "Cleanliness problem reported at the property",
    IncidentCategory.DAMAGE: "Damage reported at the property",
    IncidentCategory.OTHER: "Unclassified problem reported at the property",
}

#: **The admission condition of rule 11, declared where a test can read it.** Every
#: `IncidentClassifier` adapter must publish the closed set its `summary` is drawn from;
#: `tests/maintenance/test_classifier_vocabulary_contract.py` refuses an adapter module that
#: does not, and drives the ones that do to prove no other string escapes.
#:
#: It exists because the obligation was previously satisfied *by construction* of this one
#: adapter and by prose on the port — neither of which survives a second implementation.
#: `IncidentClassification.summary` is an unrestricted `str`, so without this declaration a
#: real provider could paraphrase the guest's description into a rule-11 sink and nothing
#: would stop it.
SUMMARY_VOCABULARY: frozenset[str] = frozenset(_SUMMARIES.values())

#: Confidence by how much evidence was found. Two matched keywords is a text that says the
#: same thing twice; one is a plausible guess; none is not a verdict at all.
#:
#: `_UNMATCHED_CONFIDENCE` sits **below** `TenantConfig.ai_confidence_threshold`'s default of
#: 0.75 on purpose: a fault this adapter does not recognise stays `OPEN` for a human to
#: triage (R1.3), rather than being filed as `OTHER`/`MEDIUM` with an air of certainty.
_STRONG_CONFIDENCE = Decimal("0.95")
_WEAK_CONFIDENCE = Decimal("0.80")
_UNMATCHED_CONFIDENCE = Decimal("0.30")

_WORD = re.compile(r"[a-z0-9]+")


def _normalise(text: str) -> set[str]:
    """Lowercase, strip accents, split into words.

    Accents go because a guest writing "climatización" and one writing "climatizacion" are
    reporting the same fault; whole words because a substring match would classify
    "gasolinera" as a gas leak.
    """
    folded = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char for char in folded if not unicodedata.combining(char))
    return set(_WORD.findall(stripped))


def _summary_for(category: IncidentCategory) -> str:
    summary = _SUMMARIES.get(category)
    if summary is None:
        raise KeyError(f"No closed summary is declared for category {category!r}")
    return summary


class RuleBasedIncidentClassifier:
    """`IncidentClassifier`, by keyword. No state, no I/O, no randomness."""

    async def classify(
        self, *, title: str, description: str
    ) -> IncidentClassification:
        words = _normalise(f"{title} {description}")

        best_category = IncidentCategory.OTHER
        best_hits = 0
        for category, keywords in _KEYWORDS:
            hits = sum(1 for keyword in keywords if keyword in words)
            # Strictly greater, so the first category of `_KEYWORDS` wins a tie — the
            # tie-break the ordering of that tuple exists to make explicit.
            if hits > best_hits:
                best_category, best_hits = category, hits

        if best_hits == 0:
            confidence = _UNMATCHED_CONFIDENCE
        elif best_hits == 1:
            confidence = _WEAK_CONFIDENCE
        else:
            confidence = _STRONG_CONFIDENCE

        return IncidentClassification(
            category=best_category,
            severity=_SEVERITIES[best_category],
            summary=_summary_for(best_category),
            confidence=confidence,
        )
