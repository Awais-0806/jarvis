"""Tests for the deterministic mandatory-gate engine."""

from datetime import datetime

import pytest

from app.gate_engine import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    evaluate_mandatory_gates,
    evaluate_mandatory_gates_detailed,
)
from app.schemas import DecisionStatus, GateResult

PASS, FAIL, UNKNOWN = GateResult.PASS, GateResult.FAIL, GateResult.UNKNOWN


class TestBasicDecisions:
    def test_all_confident_passes_are_eligible(self, make_req):
        reqs = [make_req("R1"), make_req("R2")]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.ELIGIBLE_FOR_SCORING

    def test_returns_plain_string_compatible_value(self, make_req):
        assert evaluate_mandatory_gates([make_req()]) == "eligible_for_scoring"

    def test_empty_requirements_need_human_review(self):
        assert evaluate_mandatory_gates([]) == DecisionStatus.HUMAN_REVIEW

    def test_only_optional_requirements_need_human_review(self, make_req):
        reqs = [make_req(is_mandatory=False)]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.HUMAN_REVIEW

    def test_confident_fail_rejects(self, make_req):
        reqs = [make_req("R1"), make_req("R2", FAIL)]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.REJECT

    def test_unknown_triggers_investigate(self, make_req):
        reqs = [make_req("R1"), make_req("R2", UNKNOWN, confidence=0.0)]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.INVESTIGATE


class TestWeakEvidence:
    def test_low_confidence_fail_goes_to_human_not_reject(self, make_req):
        assert evaluate_mandatory_gates([make_req(gate_result=FAIL, confidence=0.5)]) == DecisionStatus.HUMAN_REVIEW

    def test_fail_without_evidence_goes_to_human(self, make_req):
        assert evaluate_mandatory_gates([make_req(gate_result=FAIL, evidence=False)]) == DecisionStatus.HUMAN_REVIEW

    def test_low_confidence_pass_goes_to_human(self, make_req):
        assert evaluate_mandatory_gates([make_req(confidence=0.5)]) == DecisionStatus.HUMAN_REVIEW

    def test_pass_without_evidence_goes_to_human(self, make_req):
        assert evaluate_mandatory_gates([make_req(evidence=False)]) == DecisionStatus.HUMAN_REVIEW

    def test_confidence_exactly_at_threshold_is_trusted(self, make_req):
        req = make_req(confidence=DEFAULT_CONFIDENCE_THRESHOLD)
        assert evaluate_mandatory_gates([req]) == DecisionStatus.ELIGIBLE_FOR_SCORING

    def test_custom_threshold_is_respected(self, make_req):
        req = make_req(confidence=0.6)
        assert evaluate_mandatory_gates([req], confidence_threshold=0.5) == DecisionStatus.ELIGIBLE_FOR_SCORING


class TestOptionalRequirements:
    def test_optional_fail_does_not_block(self, make_req):
        reqs = [make_req("R1"), make_req("R2", FAIL, is_mandatory=False)]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.ELIGIBLE_FOR_SCORING

    def test_optional_unknown_does_not_block(self, make_req):
        reqs = [make_req("R1"), make_req("R2", UNKNOWN, is_mandatory=False)]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.ELIGIBLE_FOR_SCORING


class TestPrecedence:
    def test_reject_beats_human_review_and_investigate(self, make_req):
        reqs = [
            make_req("R1", FAIL),
            make_req("R2", FAIL, confidence=0.3),
            make_req("R3", UNKNOWN),
        ]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.REJECT

    def test_human_review_beats_investigate(self, make_req):
        reqs = [make_req("R1", confidence=0.3), make_req("R2", UNKNOWN)]
        assert evaluate_mandatory_gates(reqs) == DecisionStatus.HUMAN_REVIEW

    def test_reasons_include_all_findings_in_precedence_order(self, make_req):
        reqs = [
            make_req("R_UNKNOWN", UNKNOWN),
            make_req("R_WEAK", confidence=0.3),
            make_req("R_FAIL", FAIL),
        ]
        result = evaluate_mandatory_gates_detailed(reqs)
        assert result.decision == DecisionStatus.REJECT
        assert len(result.reasons) == 3
        assert "[R_FAIL]" in result.reasons[0]
        assert "[R_WEAK]" in result.reasons[1]
        assert "[R_UNKNOWN]" in result.reasons[2]

    def test_eligible_has_explanatory_reason(self, make_req):
        result = evaluate_mandatory_gates_detailed([make_req()])
        assert result.reasons and "passed" in result.reasons[0]


class TestDeadline:
    def test_past_deadline_rejects(self, make_req, now, past_deadline):
        decision = evaluate_mandatory_gates([make_req()], submission_deadline=past_deadline, now=now)
        assert decision == DecisionStatus.REJECT

    def test_deadline_equal_to_now_rejects(self, make_req, now):
        assert evaluate_mandatory_gates([make_req()], submission_deadline=now, now=now) == DecisionStatus.REJECT

    def test_future_deadline_does_not_block(self, make_req, now, future_deadline):
        decision = evaluate_mandatory_gates([make_req()], submission_deadline=future_deadline, now=now)
        assert decision == DecisionStatus.ELIGIBLE_FOR_SCORING

    def test_naive_deadline_raises(self, make_req, now):
        with pytest.raises(ValueError, match="timezone-aware"):
            evaluate_mandatory_gates([make_req()], submission_deadline=datetime(2026, 12, 1), now=now)

    def test_naive_now_raises(self, make_req, future_deadline):
        with pytest.raises(ValueError, match="timezone-aware"):
            evaluate_mandatory_gates([make_req()], submission_deadline=future_deadline, now=datetime(2026, 11, 8))


class TestDeterminismAndValidation:
    def test_same_inputs_same_output(self, make_req, now, future_deadline):
        reqs = [make_req("R1"), make_req("R2", UNKNOWN), make_req("R3", confidence=0.4)]
        results = {
            evaluate_mandatory_gates_detailed(reqs, submission_deadline=future_deadline, now=now).model_dump_json()
            for _ in range(5)
        }
        assert len(results) == 1

    def test_accepts_generator_input(self, make_req):
        assert evaluate_mandatory_gates(make_req(f"R{i}") for i in range(3)) == DecisionStatus.ELIGIBLE_FOR_SCORING

    @pytest.mark.parametrize("threshold", [-0.1, 1.1])
    def test_invalid_threshold_raises(self, make_req, threshold):
        with pytest.raises(ValueError, match="confidence_threshold"):
            evaluate_mandatory_gates([make_req()], confidence_threshold=threshold)
