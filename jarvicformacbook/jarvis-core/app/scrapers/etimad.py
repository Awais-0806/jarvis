"""
Etimad "AllTendersForVisitor" listing-page scraper.

Parses the public listing HTML (bilingual EN/AR tender cards) into
structured ``TenderListing`` records. Only the *listing-level* fields
are extracted — title, buyer, reference number, deadlines, activity,
cost, and the detail-page URL/ID. The tender's internal requirements
live on the detail page (login-gated) and are extracted separately by
``crew_factory.run_crew``.

Zero-trust invariants (master directive §6.2, §6.3, §9):
  * Tender HTML is UNTRUSTED. We read specific, named elements only —
    never eval, never execute, never follow embedded instructions.
  * Every listing carries provenance: source URL, ``scraped_at``, and
    a SHA-256 of the card's raw HTML for change detection.
  * Missing/ambiguous data is returned as ``None``, never invented.
  * All datetimes are timezone-aware.

Datetime handling:
  Saudi Arabia uses a fixed UTC+3 offset (no DST). We use a fixed-offset
  timezone so this module works in slim containers that ship without the
  IANA ``tzdata`` database. ``timezone(timedelta(hours=3))`` is exactly
  equivalent to ``ZoneInfo("Asia/Riyadh")`` for current and historical
  Saudi dates.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, Tag
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Saudi Arabia — fixed offset, no DST.
SAUDI_TZ = timezone(timedelta(hours=3), name="AST")

DEFAULT_LISTING_URL = "https://tenders.etimad.sa/Tender/AllTendersForVisitor"
_ALLOWED_HOSTS = frozenset({"tenders.etimad.sa"})

# Bilingual labels used to locate fields within a card.
# Order: English first, then Arabic (both should be tried, order not critical).
_LABELS: dict[str, list[str]] = {
    "publication": ["Publication date:", "تاريخ النشر"],
    "reference": ["Reference number", "الرقم المرجعي"],
    "submission_deadline": [
        "Deadline for submitting bids",
        "آخر موعد لتقديم العروض",
    ],
    "inquiry_deadline": [
        "Deadline for receiving inquiries",
        "آخر موعد لإستلام الإستفسارات",
    ],
    "opening_datetime": [
        "Date and time of opening of offers",
        "تاريخ ووقت فتح العروض",
    ],
    "activity": ["Basic activity", "النشاط الأساسي"],
    "document_cost": [
        "Value of competition documents",
        "قيمة وثائق المنافسة",
    ],
}

_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TIME_RE = re.compile(r"\b(\d{2}):(\d{2})\b")
_HIJRI_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class TenderListing(BaseModel):
    """One tender as it appears on the public Etimad listing page.

    This is an intermediate record: it carries the tender's *metadata*
    and provenance but not its internal requirements. Those are
    extracted from the detail page by ``crew_factory.run_crew``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # --- Identity and provenance ------------------------------------------
    source_id: str = Field(
        description="data-ref attribute of the card, canonical page-level ID"
    )
    reference_number: Optional[str] = Field(
        None, description="Etimad tender reference number (e.g. 261139001353)"
    )
    detail_id: Optional[str] = Field(
        None, description="STenderId for detail-page lookup, if present"
    )
    detail_url: Optional[str] = Field(
        None,
        description="Full URL to tender detail page. None when the card's "
                    "href has no STenderId (search-page anchor only).",
    )
    source_url: str = Field(description="Listing page URL that produced this record")
    scraped_at: AwareDatetime = Field(
        default_factory=lambda: datetime.now(SAUDI_TZ),
        description="When the scraper processed this card",
    )
    card_html_sha256: str = Field(
        description="SHA-256 of the card's raw HTML for change detection"
    )

    # --- Content ----------------------------------------------------------
    title: str
    buyer: Optional[str] = Field(None, description="Main agency / buyer")
    buyer_sub_unit: Optional[str] = Field(
        None, description="Sub-department within the agency"
    )
    activity: Optional[str] = Field(
        None, description="Basic activity classification"
    )
    tender_type: Optional[str] = Field(
        None, description="e.g. public competition, direct purchase"
    )

    # --- Dates (all tz-aware, Saudi local time) ---------------------------
    publication_date: Optional[date] = None
    submission_deadline: Optional[AwareDatetime] = Field(
        None, description="Bid submission deadline (Asia/Riyadh / UTC+3)"
    )
    submission_deadline_hijri: Optional[str] = Field(
        None, description="Hijri date from tooltip, preserved verbatim"
    )
    inquiry_deadline: Optional[AwareDatetime] = None
    opening_datetime: Optional[AwareDatetime] = None

    # --- Cost -------------------------------------------------------------
    document_cost: Optional[str] = Field(
        None, description="'Free', '1500', '2000', etc. — verbatim from page"
    )


# ---------------------------------------------------------------------------
# Public API — parsing
# ---------------------------------------------------------------------------
def parse_listing_page(
    html: str, *, source_url: str = DEFAULT_LISTING_URL
) -> list[TenderListing]:
    """Parse an Etimad listing page.

    Tender HTML is treated as untrusted data: we only read specific,
    named elements and never execute or follow instructions embedded in
    the text.

    Returns a list of ``TenderListing`` records. Cards that fail to parse
    (missing data-ref, missing title) are skipped with a log warning.
    """
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.tender-card")
    if not cards:
        logger.warning(
            "No .tender-card elements found in HTML (source=%s)", source_url
        )
        return []

    results: list[TenderListing] = []
    for card in cards:
        try:
            listing = _parse_card(card, source_url)
        except Exception:  # noqa: BLE001 — one bad card must not abort the page
            logger.exception("Failed to parse one tender card (skipping)")
            continue
        if listing is not None:
            results.append(listing)

    logger.info("Parsed %d/%d tender cards", len(results), len(cards))
    return results


def to_tender_request(
    listing: TenderListing,
    *,
    requirements: Optional[list] = None,
) -> dict:
    """Bridge a listing to the shape of ``schemas.TenderEvaluationRequest``.

    Use this when the detail page is not yet available (no requirements)
    to route the listing through the deterministic gate engine, which
    will correctly return ``HUMAN_REVIEW`` because ``requirements`` is
    empty.

    When you DO have ``run_crew`` output, pass it as ``requirements`` —
    this function then produces a complete, gate-ready payload.
    """
    title = _truncate(listing.title, 256) or listing.title
    buyer = _truncate(listing.buyer, 256)
    deadline = (
        listing.submission_deadline.isoformat()
        if listing.submission_deadline
        else None
    )
    return {
        "opportunity_id": _truncate(
            listing.reference_number or listing.source_id, 256
        ),
        "title": title,
        "buyer": buyer,
        "submission_deadline": deadline,
        "requirements": requirements or [],
    }


def listings_to_json(listings: list[TenderListing], *, indent: int = 2) -> str:
    """Serialize parsed listings to JSON (ISO 8601 dates, ``+03:00`` offsets)."""
    return json.dumps(
        [listing.model_dump(mode="json") for listing in listings],
        indent=indent,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Public API — optional network helper
# ---------------------------------------------------------------------------
async def fetch_listing_html(
    url: str, *, timeout: float = 30.0, user_agent: str = "Jarvis-Scorpion/0.1"
) -> str:
    """Fetch a listing page. Only hosts in ``_ALLOWED_HOSTS`` are permitted.

    Network enforcement is Awais's Squid layer; this is defense-in-depth
    on the application side. Raises on disallowed host, non-2xx status,
    or network error.
    """
    _assert_allowed_host(url)
    # Local import keeps this module importable without httpx (tests do
    # not touch the network).
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers={"User-Agent": user_agent})
        response.raise_for_status()
        return response.text


async def scrape_listing_page(
    url: str, *, timeout: float = 30.0
) -> list[TenderListing]:
    """Fetch and parse an Etimad listing page in one call."""
    html = await fetch_listing_html(url, timeout=timeout)
    return parse_listing_page(html, source_url=url)


# ---------------------------------------------------------------------------
# Internal — card parsing
# ---------------------------------------------------------------------------
def _parse_card(card: Tag, source_url: str) -> Optional[TenderListing]:
    source_id = (card.get("data-ref") or "").strip()
    if not source_id:
        return None  # data-ref is required to reference the card later

    title, raw_url = _extract_title_and_url(card)
    if not title:
        return None  # card without a title carries no usable data

    detail_id = _extract_tender_id(raw_url)
    # A listing-page URL (no STenderId) is not a unique detail URL — it
    # points back to the search page. Treat as unknown rather than fake.
    detail_url = raw_url if detail_id is not None else None

    submission_deadline, submission_hijri = _extract_deadline(
        card, "submission_deadline"
    )
    inquiry_deadline, _ = _extract_deadline(card, "inquiry_deadline")
    opening_datetime, _ = _extract_deadline(card, "opening_datetime")

    buyer, sub_unit = _extract_buyer(card)

    card_sha256 = hashlib.sha256(str(card).encode("utf-8")).hexdigest()

    return TenderListing(
        source_id=source_id,
        reference_number=_extract_text_after_label(card, "reference"),
        detail_id=detail_id,
        detail_url=detail_url,
        source_url=source_url,
        card_html_sha256=card_sha256,
        title=title,
        buyer=buyer,
        buyer_sub_unit=sub_unit,
        activity=_extract_activity(card),
        tender_type=_extract_tender_type(card),
        publication_date=_extract_publication_date(card),
        submission_deadline=submission_deadline,
        submission_deadline_hijri=submission_hijri,
        inquiry_deadline=inquiry_deadline,
        opening_datetime=opening_datetime,
        document_cost=_extract_document_cost(card),
    )


def _extract_title_and_url(card: Tag) -> tuple[Optional[str], Optional[str]]:
    h3 = card.find("h3")
    if not h3:
        return None, None
    anchor = h3.find("a")
    if not anchor:
        return h3.get_text(strip=True) or None, None
    title = anchor.get_text(strip=True) or None
    href = anchor.get("href")
    url = href if href and href.startswith("http") else None
    return title, url


def _extract_tender_id(url: Optional[str]) -> Optional[str]:
    """Return the unquoted STenderId from a detail URL, or None."""
    if not url:
        return None
    match = re.search(r"[?&]STenderId=([^&#]+)", url)
    if not match:
        return None
    return unquote(match.group(1))


def _extract_text_after_label(card: Tag, key: str) -> Optional[str]:
    """Return the first <span> text inside the parent <div> of a labeled field."""
    labels = _LABELS[key]
    for label in card.find_all("label"):
        if label.get_text(strip=True) not in labels:
            continue
        parent = label.find_parent("div")
        if not parent:
            continue
        span = parent.find("span")
        if span:
            value = span.get_text(strip=True)
            return value or None
    return None


def _extract_buyer(card: Tag) -> tuple[Optional[str], Optional[str]]:
    """Extract ``(agency, sub_unit)`` from ``.tender-metadata .pb-2``."""
    paragraph = card.select_one(".tender-metadata .pb-2")
    if not paragraph:
        return None, None

    # Clone to avoid mutating the tree; strip the trailing "the details" link.
    clone_root = BeautifulSoup(str(paragraph), "html.parser").find("p")
    if clone_root is None:
        return None, None
    for anchor in clone_root.find_all("a"):
        anchor.decompose()

    text = clone_root.get_text(separator=" ", strip=True)
    # Source format: "Agency <span> - SubUnit</span>" → split on " - ".
    parts = re.split(r"\s*[-\u2013\u2014]\s*", text, maxsplit=1)
    agency = parts[0].strip() or None if parts else None
    sub_unit = parts[1].strip() or None if len(parts) > 1 else None
    return agency, sub_unit


def _extract_tender_type(card: Tag) -> Optional[str]:
    badge = card.select_one(".badge.badge-primary")
    if not badge:
        return None
    return badge.get_text(strip=True) or None


def _extract_activity(card: Tag) -> Optional[str]:
    labels = _LABELS["activity"]
    for label in card.find_all("label"):
        if label.get_text(strip=True) not in labels:
            continue
        sibling = label.find_next_sibling()
        if isinstance(sibling, Tag) and sibling.name == "span":
            return sibling.get_text(strip=True) or None
    return None


def _extract_publication_date(card: Tag) -> Optional[date]:
    """The publication date is inside a short ``div.col-6``.
    We pick the shortest div containing the label so we do not match a
    wrapping container that happens to include the label transitively.
    """
    labels = _LABELS["publication"]
    candidates: list[tuple[int, Tag]] = []
    for div in card.find_all("div"):
        text = div.get_text(strip=True)
        if not any(lbl in text for lbl in labels):
            continue
        if len(text) > 100:  # wrapper divs are much longer
            continue
        candidates.append((len(text), div))

    if not candidates:
        return None
    _, target = min(candidates, key=lambda item: item[0])
    match = _DATE_RE.search(target.get_text())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _extract_deadline(
    card: Tag, key: str
) -> tuple[Optional[datetime], Optional[str]]:
    """Return ``(tz_aware_datetime, hijri_string_or_none)`` for a labeled
    deadline field.

    Rules:
      * Hijri string is always preserved verbatim from the tooltip title.
      * Gregorian date+time are parsed from the visible text.
      * If a submission deadline has no visible time (rare in the sample),
        the end of the day (23:59) is used — a conservative choice that
        avoids marking a same-day tender as already expired.
    """
    labels = _LABELS[key]
    for label in card.find_all("label"):
        if label.get_text(strip=True) not in labels:
            continue
        parent = label.find_parent("div")
        if not parent:
            continue

        hijri: Optional[str] = None
        tooltip = parent.find("span", attrs={"data-toggle": "tooltip"})
        if isinstance(tooltip, Tag):
            title_attr = (tooltip.get("title") or "").strip()
            if _HIJRI_RE.match(title_attr):
                hijri = title_attr

        text = parent.get_text(separator=" ", strip=True)
        date_match = _DATE_RE.search(text)
        if not date_match:
            return None, hijri

        time_match = _TIME_RE.search(text)
        try:
            year = int(date_match.group(1))
            month = int(date_match.group(2))
            day = int(date_match.group(3))
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
            else:
                hour, minute = 23, 59  # conservative end-of-day fallback
            dt = datetime.combine(
                date(year, month, day),
                time(hour, minute),
                tzinfo=SAUDI_TZ,
            )
            return dt, hijri
        except ValueError:
            return None, hijri
    return None, None


def _extract_document_cost(card: Tag) -> Optional[str]:
    container = card.select_one(".tender-coast")
    if not container:
        return None
    span = container.find("span", class_="saudi-riyal-symbol") or container.find(
        "span"
    )
    if not isinstance(span, Tag):
        return None
    return span.get_text(strip=True) or None


# ---------------------------------------------------------------------------
# Internal — helpers
# ---------------------------------------------------------------------------
def _assert_allowed_host(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(
            f"Refusing to fetch from disallowed host {host!r}; "
            f"allowed: {sorted(_ALLOWED_HOSTS)}"
        )


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    return value[:limit] if len(value) > limit else value