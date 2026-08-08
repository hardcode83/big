"""`MockSESHospedajesAdapter` — PRD §17's MVP implementation.

EXTERNAL_DEPENDENCY: SES.Hospedajes has no credentials and no legal process in place, and
PRD §29 lists real submission among the MVP non-goals. ADR 0006 decision 4 picks Chekin as
the provider when that changes; the obligations that come with it are in
`app/guests/domain/ports.py` and are not repeated here.

"Simula submission exitosa" (PRD §17), with one addition: a **deterministic** failure path,
because R6.5 requires the `FAILED` branch to be reachable and a mock that can only succeed
makes it untestable. The trigger is an explicit flag on the constructor, not a magic value in
the data — a magic document number would be a rule someone hits by accident in production
seed data.
"""

import logging
import uuid

from app.guests.domain.ports import (
    LegalSubmission,
    SESHospedajesAdapter,
    SubmissionResult,
    SubmissionStatus,
)

logger = logging.getLogger(__name__)

#: The code the mock reports when it is asked to fail. A closed vocabulary of one, which is
#: what the real adapter will have to map its provider's errors onto.
MOCK_FAILURE_CODE = "MOCK_SUBMISSION_REJECTED"


class MockSESHospedajesAdapter(SESHospedajesAdapter):
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def submit_guest(self, *, submission: LegalSubmission) -> SubmissionResult:
        if self._fail:
            logger.info(
                "guests.mock_ses_submission_rejected",
                extra={"reservation_id": str(submission.reservation_id)},
            )
            return SubmissionResult(accepted=False, error_code=MOCK_FAILURE_CODE)
        logger.info(
            "guests.mock_ses_submission_accepted",
            # Ids only. `LegalSubmission` carries a decrypted document number and a date of
            # birth, and this is the one component that holds them — logging any part of it
            # would put the most sensitive data in the system into a store with no retention
            # policy and no tenant scoping.
            extra={
                "reservation_id": str(submission.reservation_id),
                "guest_id": str(submission.guest_id),
            },
        )
        return SubmissionResult(
            accepted=True, external_id=f"mock-ses-{uuid.uuid4().hex[:12]}"
        )

    async def get_submission_status(self, external_id: str) -> SubmissionStatus:
        return (
            SubmissionStatus.ACCEPTED
            if external_id.startswith("mock-ses-")
            else SubmissionStatus.UNKNOWN
        )
