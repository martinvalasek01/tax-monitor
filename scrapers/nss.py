"""NSS scraper — vyhledavac.nssoud.cz.

Searches for finanční agenda (Afs) with DPH keyword. The NSS search UI is
a JSF app; we POST the search form and parse result rows. Selectors target
the current public page structure — if NSS redesigns the site, adjust here.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from .base import ScrapedItem

log = logging.getLogger(__name__)

SEARCH_URL = "https://vyhledavac.nssoud.cz/"
USER_AGENT = (
    "Mozilla/5.0 (tax-monitor; +https://github.com/) "
    "Python-requests/2 — daily VAT monitoring"
)
TIMEOUT = 30
LOOKBACK_DAYS = 7   # defensive: catch anything published up to a week ago that we missed
DPH_TERMS = ("daň z přidané hodnoty", "DPH")


def fetch_nss() -> list[ScrapedItem]:
    """Return a best-effort list of recent NSS Afs decisions related to DPH.

    On any network/parsing failure, logs and returns an empty list — the monitor
    should never crash because one source broke.
    """
    try:
        return list(_fetch())
    except Exception as e:
        log.exception("NSS scraper failed: %s", e)
        return []


def _fetch() -> Iterable[ScrapedItem]:
    today = datetime.now().date()
    date_from = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%d.%m.%Y")
    date_to = today.strftime("%d.%m.%Y")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "cs,en;q=0.8"})

    # Step 1: load the landing page so we collect JSF ViewState tokens.
    landing = session.get(SEARCH_URL, timeout=TIMEOUT)
    landing.raise_for_status()
    soup = BeautifulSoup(landing.text, "lxml")
    viewstate = _extract_viewstate(soup)

    # Step 2: POST search filters. Field names follow the public form.
    form_data = {
        "javax.faces.ViewState": viewstate or "",
        "form:agenda": "Afs",
        "form:dateFrom": date_from,
        "form:dateTo": date_to,
        "form:pole_text": "daň z přidané hodnoty",
        "form:search": "Vyhledat",
    }
    resp = session.post(SEARCH_URL, data=form_data, timeout=TIMEOUT)
    resp.raise_for_status()
    results = BeautifulSoup(resp.text, "lxml")

    yield from _parse_results(results)


def _extract_viewstate(soup: BeautifulSoup) -> str | None:
    tag = soup.find("input", {"name": "javax.faces.ViewState"})
    return tag.get("value") if tag else None


SPIS_ZN_RE = re.compile(r"\b\d+\s*Afs\s*\d+/\d{4}(?:\s*-\s*\d+)?\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b")


def _parse_results(soup: BeautifulSoup) -> Iterable[ScrapedItem]:
    # The results appear as table rows or list items with links to the decision detail.
    # We scan all links and keep those that look like NSS decisions with Afs signature.
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        text = link.get_text(" ", strip=True)
        if not href or not text:
            continue

        m = SPIS_ZN_RE.search(text) or SPIS_ZN_RE.search(href)
        if not m:
            continue

        spis_zn = _normalize_spis_zn(m.group(0))
        full_url = requests.compat.urljoin(SEARCH_URL, href)

        # Date: look for a nearby YYYY-MM-DD or DD.MM.YYYY in the row's parent text.
        container = link.find_parent(["tr", "li", "div"]) or link
        container_text = container.get_text(" ", strip=True)
        item_date = _extract_date(container_text)

        if not _is_dph_related(container_text):
            continue

        yield ScrapedItem(
            source="NSS",
            item_key=spis_zn,
            title=f"{spis_zn} — {_extract_title(container_text, spis_zn)}",
            url=full_url,
            item_date=item_date or "",
        )


def _normalize_spis_zn(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip())


def _extract_date(text: str) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"


def _is_dph_related(text: str) -> bool:
    lower = text.lower()
    return any(t.lower() in lower for t in DPH_TERMS)


def _extract_title(container_text: str, spis_zn: str) -> str:
    # Best-effort: strip the spis. zn. and trim surrounding whitespace/separators.
    cleaned = container_text.replace(spis_zn, "").strip(" -–|\t")
    # Cut overly long text (the DB/emails are readable, keep ~200 chars).
    return cleaned[:200] if cleaned else spis_zn
