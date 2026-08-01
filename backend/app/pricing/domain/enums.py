import enum


class PriceRecommendationStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (PriceRecommendation.status) without a named block (§7.18)."""

    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    APPLIED_EXTERNAL = "APPLIED_EXTERNAL"
    REJECTED = "REJECTED"
