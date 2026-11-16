"""
Deterministic mandatory-gate engine.

LLM agents extract requirements and propose a PASS/FAIL/UNKNOWN result for
each one, but the final routing decision is made here, by plain rules, so it
is reproducible, auditable and testable. Given the same inputs (including the
same ``now``), this module always returns the same decision.

Decision precedence (highest wins):

    1. REJECT               - a mandatory requirement confidently fails,
                              or the submission deadline has passed.
    2. HUMAN_REVIEW         - nothing to evaluate, or an automated result is
                              too weak to trust (low confidence / no evidence).
    3. INVESTIGATE          - a mandatory requirement is still UNKNOWN.
    4. ELIGIBLE_FOR_SCORING - every mandatory gate confidently passes.

Rationale: we only auto-reject on strong evidence (a wrong rejection loses a
real opportunity silently), and we never auto-approve on weak evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from .schemas import DecisionStatus, GateEvaluation, GateResult, Requirement

# Minimum agent confidence for an automated PASS/FAIL to be acted on without
# a human. Tune with care: lowering it increases automation but also the risk
# of wrong rejections/approvals.
DEFAULT_CONFIDENCE_THRESHOLD = 0.75

# Lower number = higher precedence when several rules fire at once.
_PRECEDENCE: dict[DecisionStatus, int] = {
    DecisionStatus.REJECT: 0,
    DecisionStatus.HUMAN_REVIEW: 1,
    DecisionStatus.INVESTIGATE: 2,
    DecisionStatus.ELIGIBLE_FOR_SCORING: 3,
}


def _is_trustworthy(req: Requirement, threshold: float) -> bool:
    """A result is trustworthy only if it is confident AND backed by evidence."""
    return req.confidence >= threshold and len(req.evidence) > 0


def evaluate_mandatory_gates_detailed(
    requirements: Iterable[Requirement],
    *,
    submission_deadline: datetime | None = None,
    now: datetime | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> GateEvaluation:
    """Evaluate mandatory gates and return the decision with its reasons.

    Args:
        requirements: Requirements assessed by the agents. Optional
            (non-mandatory) requirements are ignored here; they only matter
            for later scoring.
        submission_deadline: Timezone-aware tender deadline, if known.
        now: Reference time for the deadline check. Injectable so tests and
            replays are deterministic; defaults to the current UTC time.
        confidence_threshold: Minimum confidence (0-1) for an automated
            result to be acted on.

    Returns:
        GateEvaluation with the winning decision and every reason that fired,
        so reviewers see the full picture, not just the top rule.
    """
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0.0 and 1.0")

    # Each fired rule records (decision, reason). The final decision is the
    # highest-precedence one among them.
    findings: list[tuple[DecisionStatus, str]] = []

    # --- Rule: deadline already passed -> reject -------------------------
    if submission_deadline is not None:
        if submission_deadline.tzinfo is None:
            # Comparing naive and aware datetimes is ambiguous; refuse it.
            raise ValueError("submission_deadline must be timezone-aware")
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if submission_deadline <= reference:
            findings.append(
                (DecisionStatus.REJECT, f"Submission deadline {submission_deadline.isoformat()} has passed.")
            )

    mandatory = [r for r in requirements if r.is_mandatory]

    # --- Rule: nothing to evaluate -> human review -----------------------
    # An empty list usually means extraction failed, not that the tender has
    # no requirements. Never auto-approve in that case.
    if not mandatory:
        findings.append(
            (DecisionStatus.HUMAN_REVIEW, "No mandatory requirements were extracted; manual check required.")
        )

    # --- Per-requirement rules -------------------------------------------
    for req in mandatory:
        trustworthy = _is_trustworthy(req, confidence_threshold)
        label = f"[{req.requirement_id}]"
        weakness = (
            "no supporting evidence"
            if not req.evidence
            else f"confidence {req.confidence:.2f} < {confidence_threshold:.2f}"
        )

        if req.gate_result is GateResult.FAIL:
            if trustworthy:
                findings.append((DecisionStatus.REJECT, f"{label} Mandatory requirement not met."))
            else:
                # Possible failure, but too weak to reject automatically.
                findings.append(
                    (DecisionStatus.HUMAN_REVIEW, f"{label} Possible failure needs confirmation ({weakness}).")
                )
        elif req.gate_result is GateResult.UNKNOWN:
            findings.append(
                (DecisionStatus.INVESTIGATE, f"{label} Compliance unknown; more information required.")
            )
        elif req.gate_result is GateResult.PASS and not trustworthy:
            findings.append(
                (DecisionStatus.HUMAN_REVIEW, f"{label} Pass is not well supported ({weakness}).")
            )
        # A trustworthy PASS adds no finding: it does not block eligibility.

    if not findings:
        return GateEvaluation(
            decision=DecisionStatus.ELIGIBLE_FOR_SCORING,
            reasons=["All mandatory requirements passed with sufficient confidence and evidence."],
        )

    # Pick the highest-precedence decision; keep reasons in precedence order
    # (stable sort preserves original order within the same decision).
    findings.sort(key=lambda f: _PRECEDENCE[f[0]])
    return GateEvaluation(decision=findings[0][0], reasons=[reason for _, reason in findings])


def evaluate_mandatory_gates(
    requirements: Iterable[Requirement],
    *,
    submission_deadline: datetime | None = None,
    now: datetime | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> DecisionStatus:
    """Return only the routing decision.

    The returned ``DecisionStatus`` is a ``str`` subclass, so it equals one of
    ``"human_review"``, ``"reject"``, ``"investigate"`` or
    ``"eligible_for_scoring"``. Use :func:`evaluate_mandatory_gates_detailed`
    when you also need the reasons.
    """
    return evaluate_mandatory_gates_detailed(
        requirements,
        submission_deadline=submission_deadline,
        now=now,
        confidence_threshold=confidence_threshold,
    ).decision
