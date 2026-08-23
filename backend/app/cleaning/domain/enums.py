import enum


class CleaningTaskStatus(str, enum.Enum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_REVIEW = "PENDING_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CleaningValidationStatus(str, enum.Enum):
    """ASSUMPTION: name invented — the PRD declares this enum inline
    (CleaningTask.validation_status) without a named block (§7.9)."""

    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


# Kept deliberately short, because **this docstring is published**: it becomes the
# `description` of the `CleaningAssignmentBlocker` schema in `backend/openapi.json` and is read
# by whoever integrates. The rationale that belongs to us, not to them, lives here in comments:
#
# * Two members and not a boolean `can_assign`. R3.1 asks for the *reason*, and a boolean would
#   have merged the two causes again immediately after `cleaning-assign-preconditions` D1
#   separated them in the error codes. The enum is symmetric with `CONFLICT` /
#   `PROPERTY_STATE_CONFLICT`, which is what lets one message per cause exist in both places.
# * `StrEnum` and not `str, enum.Enum` like its two neighbours above, for the reason
#   `app/core/error_codes.py` writes down: members serialise exactly like the string literals
#   they stand for. The neighbours predate that convention and are not worth churning.
class CleaningAssignmentBlocker(enum.StrEnum):
    """Which party refuses to assign a cleaning task: its own status, or its property's state."""

    TASK_STATUS = "TASK_STATUS"
    PROPERTY_STATE = "PROPERTY_STATE"
