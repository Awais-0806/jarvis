"""
Global tender feed for the dashboard — SAMPLE DATA for now.
 
The three tenders below are hand-written demo records, not real notices. They are shaped like
what the live connectors will return (UK Find a Tender, US SAM.gov, EU TED) so the rest of the
pipeline (matchmaker agent, pitch writer, UI) can be built and shown end to end. Every record
carries ``is_mock=True`` and a ``DEMO-`` reference, and the API response says ``mode="mock"``,
so sample data can never be mistaken for a live opportunity.
 
When a real connector lands, replace ``list_tenders``/``get_tender`` and keep the schema.
 
Deadlines are computed from "today" so the samples never show as expired during a demo.
"""
 
from __future__ import annotations
 
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
 
from pydantic import AwareDatetime, Field
 
from .schemas import StrictModel
 
# Goes into a URL path: keep it to a strict allowlist (same shape the UI accepts).
TENDER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
 
MOCK_NOTICE = (
    "Sample data for demonstration. These are not live notices: the Find a Tender, SAM.gov "
    "and TED connectors are not wired in yet."
)
 
# Upper bound on the text handed to the LLM for one tender (~300 tokens of a 4096 window).
MAX_BRIEF_CHARS = 1300
 
 
class GlobalTender(StrictModel):
    """One tender as shown on the dashboard and handed (as a brief) to the agents."""
 
    id: str = Field(pattern=TENDER_ID_PATTERN)
    reference: str = Field(max_length=64)
    title: str = Field(max_length=200)
    buyer: str = Field(max_length=200)
    country: str = Field(max_length=60)
    region: Literal["UK", "USA", "EU"]
    source_portal: str = Field(max_length=80)
    procedure: str = Field(max_length=120)
    classification: str = Field(max_length=200)
    estimated_value: str = Field(max_length=60)
    published_on: date
    submission_deadline: AwareDatetime
    summary: str = Field(max_length=900)
    required_capabilities: list[str] = Field(max_length=8)
    mandatory_requirements: list[str] = Field(max_length=8)
    is_mock: bool
 
    def brief(self) -> str:
        """Compact plain-text version for prompts and retrieval. Bounded: tender text is
        untrusted once real portals feed this, and the model's context window is small."""
        text = (
            f"Title: {self.title}\n"
            f"Buyer: {self.buyer} ({self.country})\n"
            f"Summary: {self.summary}\n"
            f"Required capabilities: {'; '.join(self.required_capabilities)}\n"
            f"Mandatory requirements: {'; '.join(self.mandatory_requirements)}"
        )
        return text[:MAX_BRIEF_CHARS]
 
 
class GlobalTenderList(StrictModel):
    items: list[GlobalTender] = Field(max_length=50)
    mode: Literal["mock", "live"]
    notice: str = Field(max_length=300)
 
 
class PitchRequest(StrictModel):
    """Body of ``POST /global-tenders/{id}/pitch`` (optional)."""
 
    # False: reuse the pitch already drafted for this tender since core started, if any.
    regenerate: bool = False
 
 
def _deadline(today: date, days_ahead: int, hour_utc: int) -> datetime:
    return datetime.combine(today + timedelta(days=days_ahead), time(hour_utc, 0), tzinfo=UTC)
 
 
def list_tenders(today: date | None = None) -> list[GlobalTender]:
    """Return the sample tenders. ``today`` is injectable so tests are deterministic."""
    today = today or datetime.now(UTC).date()
    return [
        GlobalTender(
            id="demo-uk-001",
            reference="DEMO-FTS-UK-001",
            title="Conversational Voice AI Agents for Citizen Contact Centres",
            buyer="HM Revenue & Customs",
            country="United Kingdom",
            region="UK",
            source_portal="Find a Tender (sample)",
            procedure="Competitive flexible procedure",
            classification="CPV 72212517 IT software development; 79512000 Call centre services",
            estimated_value="GBP 2.4m over 24 months",
            published_on=today - timedelta(days=6),
            submission_deadline=_deadline(today, 21, 12),
            summary=(
                "Design, build and run AI voice agents that answer routine inbound calls end "
                "to end, hand over to human advisers with full context, and scale to several "
                "hundred concurrent calls at peak. Agents must look up and update records in "
                "the authority's CRM during the call, score caller sentiment live, and keep a "
                "complete audit log of every automated decision."
            ),
            required_capabilities=[
                "Real-time speech-to-text and text-to-speech pipeline",
                "LLM agents with tool access to CRM and booking systems",
                "Autoscaling to 300+ concurrent calls",
                "Live sentiment scoring and human handover",
                "Multi-tenant configuration per business unit",
            ],
            mandatory_requirements=[
                "UK data residency for call audio and transcripts",
                "Cyber Essentials Plus certification",
                "Staff eligible for BPSS clearance",
            ],
            is_mock=True,
        ),
        GlobalTender(
            id="demo-us-001",
            reference="DEMO-SAM-US-001",
            title="Smart Building IoT and AI Energy Optimization for Federal Facilities",
            buyer="General Services Administration, Public Buildings Service",
            country="United States",
            region="USA",
            source_portal="SAM.gov (sample)",
            procedure="Combined synopsis/solicitation, full and open competition",
            classification="NAICS 541512 Computer Systems Design Services; PSC DA01",
            estimated_value="USD 6.5m, base year plus two options",
            published_on=today - timedelta(days=11),
            submission_deadline=_deadline(today, 34, 19),
            summary=(
                "Pilot an intelligent building platform across twelve high-rise federal office "
                "towers: networked IoT sensors and dynamic (electrochromic) glazing controlled "
                "by on-device machine learning to cut energy use, computer-vision inspection of "
                "facades to find damage early, and a tamper-evident record of energy savings "
                "and carbon reductions for audit. Telemetry must stream to a cloud dashboard "
                "in near real time."
            ),
            required_capabilities=[
                "IoT sensor networks with MQTT telemetry",
                "Edge ML inference for building energy control",
                "Computer-vision facade inspection",
                "Immutable ledger for energy and carbon records",
                "Cloud dashboards on Kubernetes",
            ],
            mandatory_requirements=[
                "Active SAM.gov registration with a Unique Entity ID",
                "FedRAMP Moderate authorised cloud hosting",
                "NIST SP 800-53 security controls",
            ],
            is_mock=True,
        ),
        GlobalTender(
            id="demo-eu-001",
            reference="DEMO-TED-EU-001",
            title="Generative AI Knowledge Assistant for Regulatory and Compliance Staff",
            buyer="European Investment Bank",
            country="Luxembourg",
            region="EU",
            source_portal="TED - Tenders Electronic Daily (sample)",
            procedure="Open procedure",
            classification="CPV 72000000 IT services; 48610000 Database systems",
            estimated_value="EUR 3.2m over 36 months",
            published_on=today - timedelta(days=4),
            submission_deadline=_deadline(today, 28, 11),
            summary=(
                "Deliver a retrieval-augmented generation (RAG) assistant over the bank's "
                "regulatory, risk and policy document base so that compliance and treasury "
                "staff get answers with citations to the source paragraph. The service must "
                "stay consistent across offices in many regions, run on managed Kubernetes "
                "with infrastructure as code, and report answer accuracy against a test set."
            ),
            required_capabilities=[
                "RAG pipeline with vector search and source citations",
                "LLM agents for compliance queries",
                "Banking or financial-services delivery experience",
                "Kubernetes and Terraform on a major cloud",
                "Measured answer-accuracy evaluation",
            ],
            mandatory_requirements=[
                "Data processed and stored inside the EU (GDPR)",
                "ISO/IEC 27001 certification",
                "Two comparable references from the last three years",
            ],
            is_mock=True,
        ),
    ]
 
 
def get_tender(tender_id: str, today: date | None = None) -> GlobalTender | None:
    """Look up one tender by id; ``None`` if it is not listed."""
    return next((t for t in list_tenders(today) if t.id == tender_id), None)


def fetch_global_tenders(region: str = "") -> str:
    """Fetch current global public tenders across UK (Find a Tender), US (SAM.gov), and EU (TED).

    Returns active international tender opportunities with title, buyer, value, deadline,
    and requirements. Use this tool whenever the CEO asks for global, UK, US, or EU tenders.
    """
    tenders = list_tenders()
    if region:
        reg = region.strip().upper()
        filtered = [t for t in tenders if t.region == reg or reg in t.country.upper()]
        if filtered:
            tenders = filtered
    lines = []
    for t in tenders:
        lines.append(
            f"[{t.region}] {t.title}\n"
            f"  Reference: {t.reference} | Buyer: {t.buyer} ({t.country})\n"
            f"  Portal: {t.source_portal} | Estimated Value: {t.estimated_value}\n"
            f"  Deadline: {t.submission_deadline.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"  Summary: {t.summary}\n"
            f"  Required Capabilities: {'; '.join(t.required_capabilities)}\n"
            f"  Mandatory Requirements: {'; '.join(t.mandatory_requirements)}"
        )
    return "\n\n".join(lines)


try:
    from crewai.tools import tool as _crewai_tool

    fetch_global_tenders = _crewai_tool("fetch_global_tenders")(fetch_global_tenders)
except ImportError:
    pass
