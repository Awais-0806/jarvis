"""Shared pytest fixtures and path setup for jarvis-core tests."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Make the `app` package importable when pytest runs from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas import EvidenceRef, GateResult, Requirement  # noqa: E402

# Fixed reference time so deadline-based tests are deterministic.
FIXED_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def make_req():
    """Factory for Requirement objects with sensible, overridable defaults."""

    def _make(
        requirement_id: str = "R1",
        gate_result: GateResult = GateResult.PASS,
        confidence: float = 0.9,
        evidence: bool = True,
        is_mandatory: bool = True,
    ) -> Requirement:
        return Requirement(
            requirement_id=requirement_id,
            description=f"Requirement {requirement_id}",
            is_mandatory=is_mandatory,
            gate_result=gate_result,
            confidence=confidence,
            evidence=[EvidenceRef(document_id="tender.pdf", page=1)] if evidence else [],
        )

    return _make


@pytest.fixture
def future_deadline() -> datetime:
    return FIXED_NOW + timedelta(days=7)


@pytest.fixture
def past_deadline() -> datetime:
    return FIXED_NOW - timedelta(days=1)
