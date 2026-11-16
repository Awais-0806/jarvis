"""Tests for Pydantic schema validation rules."""

import pytest
from pydantic import ValidationError

from app.schemas import DecisionStatus, EvidenceRef, GateResult, Requirement, TenderEvaluationRequest


def _req(rid: str = "R1", **overrides) -> dict:
    return {"requirement_id": rid, "description": "Must hold ISO 9001", **overrides}


class TestRequirement:
    def test_defaults_are_conservative(self):
        req = Requirement(**_req())
        assert req.is_mandatory is True
        assert req.gate_result is GateResult.UNKNOWN
        assert req.confidence == 0.0
        assert req.evidence == []

    @pytest.mark.parametrize("confidence", [-0.01, 1.01])
    def test_confidence_must_be_in_range(self, confidence):
        with pytest.raises(ValidationError):
            Requirement(**_req(confidence=confidence))

    def test_unknown_fields_rejected(self):
        with pytest.raises(ValidationError):
            Requirement(**_req(unexpected="x"))

    def test_invalid_gate_result_rejected(self):
        with pytest.raises(ValidationError):
            Requirement(**_req(gate_result="maybe"))

    def test_whitespace_is_stripped(self):
        assert Requirement(**_req(rid="  R1  ")).requirement_id == "R1"

    def test_blank_description_rejected(self):
        with pytest.raises(ValidationError):
            Requirement(requirement_id="R1", description="   ")


class TestEvidenceRef:
    def test_page_must_be_positive(self):
        with pytest.raises(ValidationError):
            EvidenceRef(document_id="doc.pdf", page=0)

    def test_document_id_required(self):
        with pytest.raises(ValidationError):
            EvidenceRef(document_id="")


class TestTenderEvaluationRequest:
    def test_duplicate_requirement_ids_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate requirement_id"):
            TenderEvaluationRequest(opportunity_id="T1", title="Tender", requirements=[_req("R1"), _req("R1")])

    def test_naive_deadline_rejected(self):
        with pytest.raises(ValidationError):
            TenderEvaluationRequest(opportunity_id="T1", title="Tender", submission_deadline="2026-12-01T12:00:00")

    def test_aware_deadline_accepted(self):
        req = TenderEvaluationRequest(opportunity_id="T1", title="Tender", submission_deadline="2026-12-01T12:00:00Z")
        assert req.submission_deadline.tzinfo is not None


def test_decision_status_string_values():
    assert {s.value for s in DecisionStatus} == {"human_review", "reject", "investigate", "eligible_for_scoring"}
