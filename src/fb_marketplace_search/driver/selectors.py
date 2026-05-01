"""All Marketplace CSS/XPath/URL-param strings live here.

Per architect §6 risk #1: this is the *first file* to edit when Marketplace
breaks us. Centralizing makes the canary loud — fixture-based parser tests
in `tests/integration/` should reference these constants and fail noisily
when a string drifts in real captures.

Keep this file thin and entirely declarative. No logic.
"""

from __future__ import annotations

# --- URL construction --------------------------------------------------------
# Marketplace search-results URL skeleton. We prefer URL params over
# click-driven filtering for determinism (architect §2 module 5).
MARKETPLACE_BASE = "https://www.facebook.com"
SEARCH_PATH = "/marketplace/search"

# URL query-param keys (Marketplace's actual param names — change here when
# Meta renames them).
PARAM_QUERY = "query"
PARAM_PRICE_MIN = "minPrice"
PARAM_PRICE_MAX = "maxPrice"
PARAM_DAYS_LISTED = "daysSinceListed"
PARAM_RADIUS_KM = "radius"
PARAM_CONDITION = "itemCondition"

# Marketplace condition enum values.
CONDITION_PARAM_VALUES = {
    "new": "new",
    "used-like-new": "used_like_new",
    "used-good": "used_good",
    "used-fair": "used_fair",
}

# --- Result-card harvest -----------------------------------------------------
# CSS selectors for the search-results page. Marketplace uses generated class
# names heavily; we target stable role/data attributes when possible.
RESULTS_CONTAINER = '[role="main"]'
RESULT_CARD = 'a[href*="/marketplace/item/"]'
RESULT_CARD_PRICE = '[aria-label*="price" i], span[dir="auto"]'
RESULT_CARD_TITLE = 'span[dir="auto"]'
RESULT_CARD_LOCATION = 'span[class*="location"], span[dir="auto"]:has(+ span)'
RESULT_CARD_IMAGE = 'img'

# Empty-results sentinel ("No results found").
EMPTY_RESULTS_TEXT = "No results"

# --- Listing detail (for lazy second-pass description fetch, §5 Layer 7) -----
DETAIL_DESCRIPTION = '[class*="description"], div[data-testid="marketplace-description"]'
DETAIL_CONDITION_LABEL = 'span:has-text("Condition")'

# --- Login-wall canary -------------------------------------------------------
LOGIN_WALL_TEXT = "log in"
LOGIN_FORM_INPUT = 'input[name="email"]'

# --- Listing id extraction (from a card URL) ---------------------------------
# A Marketplace card URL looks like .../marketplace/item/<id>/...
LISTING_ID_URL_REGEX = r'/marketplace/item/(?P<id>\d+)'
