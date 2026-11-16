"""Source acquisition layer — scrapers for external tender portals."""

from .etimad import (
    DEFAULT_LISTING_URL,
    TenderListing,
    fetch_listing_html,
    listings_to_json,
    parse_listing_page,
    scrape_listing_page,
    to_tender_request,
)

__all__ = [
    "DEFAULT_LISTING_URL",
    "TenderListing",
    "fetch_listing_html",
    "listings_to_json",
    "parse_listing_page",
    "scrape_listing_page",
    "to_tender_request",
]