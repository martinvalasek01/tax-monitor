"""GFŘ novinky scraper — financnisprava.gov.cz/cs/financni-sprava/novinky.

Pulls the latest news list and keeps items whose title/perex mentions DPH.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .base import ScrapedItem

log = logging.getLogger(__name__)

NOVINKY_URL = "https://www.financnisprava.gov.cz/cs/financni-sprava/novinky"
USER_AGENT = (
    "Mozilla/5.0 (tax-monitor; +https://github.com/) "
    "Python-requests/2 — daily VAT monitoring"
)
TIMEOUT = 30
DPH_TERMS = ("dph", "daň z přidané hodnoty", "daně z přidané hodnoty")


def fetch_gfr() -> list[ScrapedItem]:
    try:
        return list(_fetch())
    except Exception as e:
        log.exception("GFŘ scraper failed: %s", e)
        return []


def _fetch() -> Iterable[ScrapedItem]:
    resp = requests.get(
        NOVINKY_URL,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "cs,en;q=0.8"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # Generic selector: news listings are built from <article> or list items
    # containing an <a> headline. We iterate widely and filter by DPH keyword.
    candidates = soup.select("article, li.news-item, div.news-item, .news-list li, .content-main li")
    if not candidates:
        candidates = soup.select("a[href*='/cs/financni-sprava/novinky/']")

    seen_urls: set[str] = set()
    for node in candidates:
        link = node if node.name == "a" else node.find("a", href=True)
        if not link:
            continue
        href = link.get("href", "")
        title = link.get_text(" ", strip=True)
        if not href or not title:
            continue

        url = urljoin(NOVINKY_URL, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        context = node.get_text(" ", strip=True) if node is not link else title
        if not _is_dph_related(context):
            continue

        item_date = _extract_date(context)

        yield ScrapedItem(
            source="GFŘ",
            item_key=url,
            title=title[:250],
            url=url,
            item_date=item_date or "",
        )


def _is_dph_related(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in DPH_TERMS)


DATE_RE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b")


def _extract_date(text: str) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"
