"""EUR-Lex scraper — new CJEU judgments mentioning "value added tax".

Uses the EUR-Lex advanced search RSS feed (Case law, judgments only), so we
don't have to scrape the HTML search UI. Each entry in the feed has a CELEX
identifier which we use as stable dedup key.
"""
from __future__ import annotations

import logging
from typing import Iterable

import feedparser

from .base import ScrapedItem

log = logging.getLogger(__name__)

# EUR-Lex "expert search" RSS: judgments (DTT_6) with the phrase "value added tax",
# sorted by document date descending. The URL is taken from EUR-Lex's own
# "Save as RSS" button on a filtered search; change the qid timestamp if needed.
SEARCH_RSS = (
    "https://eur-lex.europa.eu/EN/search.html"
    "?SUBDOM_INIT=EU_CASE_LAW"
    "&DTS_DOM=EU_LAW"
    "&typeOfActStatus=COURT_JUDGMENT"
    "&type=advanced"
    "&lang=en"
    "&andText0=%22value+added+tax%22"
    "&sortOneOrder=desc"
    "&sortOne=DD"
    "&format=RSS"
)
USER_AGENT = "tax-monitor/1.0 (+https://github.com/)"


def fetch_eurlex() -> list[ScrapedItem]:
    try:
        return list(_fetch())
    except Exception as e:
        log.exception("EUR-Lex scraper failed: %s", e)
        return []


def _fetch() -> Iterable[ScrapedItem]:
    feed = feedparser.parse(SEARCH_RSS, agent=USER_AGENT, request_headers={"Accept": "application/rss+xml"})
    if feed.bozo:
        log.warning("EUR-Lex feed parse warning: %s", feed.bozo_exception)

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        celex = _extract_celex(link) or link
        item_date = _extract_date(entry)

        yield ScrapedItem(
            source="EUR-Lex",
            item_key=celex,
            title=title[:250],
            url=link,
            item_date=item_date,
        )


def _extract_celex(url: str) -> str | None:
    # EUR-Lex URLs include "CELEX:<id>" or "CELEX%3A<id>" in query string or path.
    import re
    m = re.search(r"CELEX[:%]3?A?([0-9A-Z]+)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_date(entry) -> str:
    # feedparser exposes published_parsed as a time.struct_time
    if getattr(entry, "published_parsed", None):
        t = entry.published_parsed
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
    return entry.get("published", "") or ""
