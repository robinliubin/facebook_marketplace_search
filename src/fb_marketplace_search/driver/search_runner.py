"""Drive the browser: build URL, scroll-paginate, harvest cards.

The harvest step is split into two halves:

  - `harvest_from_html(html, ...)` — pure function over a captured HTML string,
    used by integration tests against canned fixtures (no browser).
  - `run_search(...)` — live: opens the browser, builds the URL with the
    parsed filters, scrolls N viewport-heights, captures the page HTML,
    delegates to `harvest_from_html`.

Per architect §6 risk #1: the HTML parser uses selectors from
`driver.selectors` so fixture tests catch drift before users do.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlencode, urljoin

from ..config import Settings
from ..parser import ParsedQuery
from . import selectors


class SelectorDrift(RuntimeError):
    """Zero result cards parsed where >= 1 was expected. Layer-5 canary."""


def build_search_url(query: ParsedQuery) -> str:
    params: dict[str, str] = {}
    if query.keywords:
        params[selectors.PARAM_QUERY] = query.keywords
    if query.price_min is not None:
        params[selectors.PARAM_PRICE_MIN] = str(int(query.price_min))
    if query.price_max is not None:
        params[selectors.PARAM_PRICE_MAX] = str(int(query.price_max))
    if query.distance_km is not None:
        params[selectors.PARAM_RADIUS_KM] = str(int(query.distance_km))
    if query.recency_days is not None:
        params[selectors.PARAM_DAYS_LISTED] = str(int(query.recency_days))
    if query.condition is not None:
        cond = selectors.CONDITION_PARAM_VALUES.get(query.condition)
        if cond:
            params[selectors.PARAM_CONDITION] = cond
    qs = urlencode(params, doseq=False)
    base = urljoin(selectors.MARKETPLACE_BASE, selectors.SEARCH_PATH)
    return f"{base}?{qs}" if qs else base


# ---------------------------------------------------------------------------
# HTML harvest (no browser)
# ---------------------------------------------------------------------------


@dataclass
class _CardRaw:
    marketplace_id: str
    url: str
    title: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    location: Optional[str] = None
    distance_km: Optional[float] = None
    listed_at: Optional[str] = None
    condition: Optional[str] = None
    seller_id: Optional[str] = None
    image_url: Optional[str] = None
    description: Optional[str] = None


_LISTING_ID_RE = re.compile(selectors.LISTING_ID_URL_REGEX)
_PRICE_RE = re.compile(r'(?P<currency>CA?\$|US\$|\$|EUR|€)?\s*(?P<amount>\d{1,3}(?:[\s,]?\d{3})*(?:\.\d+)?)')
_KM_RE = re.compile(r'(?P<km>\d+(?:\.\d+)?)\s*km', re.IGNORECASE)


def _parse_price(text: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    if not text:
        return (None, None)
    m = _PRICE_RE.search(text)
    if not m:
        return (None, None)
    amount = m.group("amount").replace(",", "").replace(" ", "")
    try:
        price = float(amount)
    except ValueError:
        return (None, None)
    sym = m.group("currency") or ""
    if "CA" in sym or sym == "C$":
        currency = "CAD"
    elif "US" in sym:
        currency = "USD"
    elif sym in ("€", "EUR"):
        currency = "EUR"
    elif sym == "$":
        currency = "CAD"
    else:
        currency = None
    return (price, currency)


def _parse_distance(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = _KM_RE.search(text)
    return float(m.group("km")) if m else None


class _CardCollector(HTMLParser):
    """Minimal stdlib-only HTML parser. We don't need a true DOM — Marketplace
    cards in v1 fixtures are well-formed enough that `<a href="/marketplace/item/...">`
    plus the inner text and a sibling `<img>` element gives us everything we need.

    For robustness against more complex live pages we recommend the JSON
    `__NEXT_DATA__` blob the live runner extracts (out of scope for v1 fixtures).
    """

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[_CardRaw] = []
        self._current_a: Optional[_CardRaw] = None
        self._a_depth = 0
        self._inside_a_text: list[str] = []
        self._current_img_src: Optional[str] = None
        self._capture = False
        # Convenience: data-* per-card overrides
        self._current_data: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = dict(attrs)
        if tag == "a":
            href = a.get("href") or ""
            m = _LISTING_ID_RE.search(href)
            if m:
                # Capture data-* attributes that fixtures may use to encode
                # structured fields cleanly without DOM-mining.
                self._current_data = {
                    k[5:]: v for k, v in a.items() if k.startswith("data-") and v is not None
                }
                self._current_a = _CardRaw(
                    marketplace_id=m.group("id"),
                    url=urljoin(selectors.MARKETPLACE_BASE, href),
                )
                self._a_depth = 1
                self._inside_a_text = []
                self._current_img_src = None
                self._capture = True
                return
        if self._capture:
            if tag == "a":
                self._a_depth += 1
            if tag == "img":
                src = a.get("src")
                if src and self._current_img_src is None:
                    self._current_img_src = src

    def handle_endtag(self, tag: str) -> None:
        if not self._capture:
            return
        if tag == "a":
            self._a_depth -= 1
            if self._a_depth == 0:
                # Finalize current card.
                card = self._current_a
                assert card is not None
                joined = " ".join(t.strip() for t in self._inside_a_text if t.strip())
                # Apply data-* overrides first; they win.
                d = self._current_data
                card.title = d.get("title") or (joined.split(" · ")[0] if joined else None)
                if "price" in d:
                    try:
                        card.price = float(d["price"])
                    except ValueError:
                        card.price = None
                else:
                    price, currency = _parse_price(joined)
                    card.price = price
                    card.currency = card.currency or currency
                if "currency" in d:
                    card.currency = d["currency"]
                if "location" in d:
                    card.location = d["location"]
                if "distance_km" in d:
                    try:
                        card.distance_km = float(d["distance_km"])
                    except ValueError:
                        card.distance_km = None
                else:
                    card.distance_km = _parse_distance(joined)
                if "listed_at" in d:
                    card.listed_at = d["listed_at"]
                if "condition" in d:
                    card.condition = d["condition"]
                if "seller_id" in d:
                    card.seller_id = d["seller_id"]
                if "description" in d:
                    card.description = d["description"]
                card.image_url = self._current_img_src
                self.cards.append(card)
                self._current_a = None
                self._capture = False
                self._current_data = {}

    def handle_data(self, data: str) -> None:
        if self._capture and data:
            self._inside_a_text.append(data)


def harvest_from_html(html: str) -> list[dict]:
    """Parse a captured Marketplace search-results page HTML into a list of raw
    dicts (one per result card). `marketplace_id` and `url` are guaranteed
    present; everything else may be None.
    """
    if not html or selectors.EMPTY_RESULTS_TEXT.lower() in html.lower():
        return []
    p = _CardCollector()
    p.feed(html)
    out = []
    # Within-run duplicates are deduped at the SQL layer per architecture §7.6
    # (INSERT OR IGNORE on search_results retains the earliest-seen position).
    # Do NOT pre-dedup here — the SQL layer is the single source of truth and
    # the CLI logs the drop count from its return value.
    for c in p.cards:
        out.append({
            "marketplace_id": c.marketplace_id,
            "url": c.url,
            "title": c.title,
            "description": c.description,
            "price": c.price,
            "currency": c.currency,
            "location": c.location,
            "distance_km": c.distance_km,
            "listed_at": c.listed_at,
            "condition": c.condition,
            "seller_id": c.seller_id,
            "image_url": c.image_url,
        })
    return out


# ---------------------------------------------------------------------------
# Live runner
# ---------------------------------------------------------------------------


def run_search(
    page,
    query: ParsedQuery,
    *,
    pages: int,
    settings: Settings,
) -> tuple[list[dict], int]:
    """Drive the page through `pages` viewport-heights of infinite scroll and
    return (raw_cards, pages_fetched). Live, requires a Playwright Page.
    """
    url = build_search_url(query)
    page.goto(url, wait_until="domcontentloaded")

    # Each "page" is one viewport-scroll; wait briefly for new cards to mount.
    fetched = 0
    last_card_count = 0
    for i in range(pages):
        try:
            page.evaluate("window.scrollBy(0, window.innerHeight)")
        except Exception:
            break
        # Settle window: 5s idle or a card-count delta.
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                cur = page.locator(selectors.RESULT_CARD).count()
            except Exception:
                cur = last_card_count
            if cur > last_card_count:
                last_card_count = cur
                break
            time.sleep(0.25)
        fetched += 1

    html = page.content()
    cards = harvest_from_html(html)
    if not cards:
        # Layer-5 canary: dump page HTML for debugging, but only if not the
        # legitimate empty-results state.
        if selectors.EMPTY_RESULTS_TEXT.lower() not in html.lower():
            try:
                Path(settings.last_failure_path).write_text(html, encoding="utf-8")
            except Exception:
                pass
            raise SelectorDrift(
                f"Zero cards parsed from non-empty results page; HTML dumped to "
                f"{settings.last_failure_path}"
            )
    return (cards, fetched)
