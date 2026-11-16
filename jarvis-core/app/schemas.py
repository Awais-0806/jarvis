"""
Data contracts for the Jarvis tender-evaluation pipeline.

These Pydantic models are the single source of truth for what flows between
the CrewAI agents, the deterministic gate engine, the API layer and the CSV
exporter. Keeping them strict (extra fields forbidden, bounded sizes, timezone-
aware datetimes) means malformed agent output is rejected at the boundary
instead of silently propagating into a bid/no-bid decision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Shared constraints
# ---------------------------------------------------------------------------
# Bounded string/list sizes protect the API from oversized payloads and keep
# CSV exports readable. Adjust centrally here if requirements change.
ShortText = Annotated[str, Field(min_length=1, max_length=256)]
LongText = Annotated[str, Field(max_length=5_000)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class StrictModel(BaseModel):
    """Base model: reject unknown fields and trim surrounding whitespace."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=False,
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class GateResult(str, Enum):
    """Outcome of checking a single requirement against the company profile."""

    PASS = "pass"        # Evidence shows the requirement is met.
    FAIL = "fail"        # Evidence shows the requirement is NOT met.
    UNKNOWN = "unknown"  # Not enough information to decide either way.


class DecisionStatus(str, Enum):
    """Overall routing decision produced by the mandatory gate engine.

    Inherits from ``str`` so values compare equal to their plain-string form
    (e.g. ``DecisionStatus.REJECT == "reject"``) and serialise cleanly to JSON.
    """

    HUMAN_REVIEW = "human_review"
    REJECT = "reject"
    INVESTIGATE = "investigate"
    ELIGIBLE_FOR_SCORING = "eligible_for_scoring"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------
class EvidenceRef(StrictModel):
    """A pointer to the source material that backs a gate result.

    Every automated claim should be traceable to a document location so a
    human reviewer can verify it quickly.
    """

    document_id: ShortText = Field(description="ID or filename of the source document.")
    page: int | None = Field(default=None, ge=1, description="1-based page number, if known.")
    section: ShortText | None = Field(default=None, description="Section/clause reference, e.g. '4.2.1'.")
    excerpt: LongText | None = Field(default=None, description="Verbatim quote supporting the claim.")


class Requirement(StrictModel):
    """A single tender requirement and the agent's assessment of it."""

    requirement_id: ShortText
    description: LongText = Field(min_length=1)
    is_mandatory: bool = Field(
        default=True,
        description="Mandatory requirements are pass/fail gates; optional ones only affect scoring.",
    )
    gate_result: GateResult = GateResult.UNKNOWN
    confidence: Confidence = Field(
        default=0.0,
        description="Agent confidence in gate_result, 0.0 (none) to 1.0 (certain).",
    )
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=50)
    notes: LongText | None = None


class TenderEvaluationRequest(StrictModel):
    """Inbound payload for evaluating one tender opportunity."""

    opportunity_id: ShortText
    title: ShortText
    buyer: ShortText | None = None
    submission_deadline: AwareDatetime | None = Field(
        default=None,
        description="Timezone-aware deadline (ISO 8601 with offset, e.g. 2026-12-01T12:00:00Z).",
    )
    requirements: list[Requirement] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _requirement_ids_unique(self) -> TenderEvaluationRequest:
        # Duplicate IDs would make audit trails and CSV rows ambiguous.
        seen: set[str] = set()
        duplicates: set[str] = set()
        for req in self.requirements:
            if req.requirement_id in seen:
                duplicates.add(req.requirement_id)
            seen.add(req.requirement_id)
        if duplicates:
            raise ValueError(f"Duplicate requirement_id values: {sorted(duplicates)}")
        return self


class OpportunityAssessment(TenderEvaluationRequest):
    """A tender opportunity together with its gate decision.

    Extends the request with output-only fields populated by the gate engine.
    """

    decision_status: DecisionStatus
    decision_reasons: list[str] = Field(default_factory=list)
    evaluated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class GateEvaluation(StrictModel):
    """Detailed result of the gate engine: the decision plus why it was made."""

    decision: DecisionStatus
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Chat (dashboard -> core)
# ---------------------------------------------------------------------------
# Matches the UI's limits: chat_input max_chars=4000, conversation ids are uuid4 hex.
class ChatRequest(StrictModel):
    """One chat message from the CEO dashboard."""

    message: str = Field(min_length=1, max_length=4_000)
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class JobState(str, Enum):
    """Lifecycle of a background chat job (mirrors ``jobs.JobStatus``)."""

    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# Job ids are uuid4 hex; the pattern also guards the GET /jobs/{job_id} path parameter.
JOB_ID_PATTERN = r"^[0-9a-f]{32}$"


class ChatJobResponse(StrictModel):
    """State of a chat job. ``reply`` is set when done, ``error`` when it failed."""

    job_id: str = Field(pattern=JOB_ID_PATTERN)
    status: JobState
    reply: str | None = Field(default=None, max_length=20_000)
    error: str | None = Field(default=None, max_length=500)
