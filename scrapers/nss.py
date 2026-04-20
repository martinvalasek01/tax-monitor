"""NSS scraper — vyhledavac.nssoud.cz.

The search form is an ASP.NET MVC app with a deep model-binding schema
(vyhledavaciSekce[i].vyhledavaciPodminka[j]...). We harvest every input
from the landing page — including the antiforgery token — override only
the two values we care about (full-text phrase + date range), and POST
to /Home/Index?formular=1&zobrazeniVysledkuVolba=2. Results come back
as table#tresults rows.

Selectors target the current public page structure — if NSS redesigns
the site, adjust here.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from .base import ScrapedItem

log = logging.getLogger(__name__)

BASE_URL = "https://vyhledavac.nssoud.cz/"
SUBMIT_URL = "https://vyhledavac.nssoud.cz/Home/Index?formular=1&zobrazeniVysledkuVolba=2"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) tax-monitor/1.0 Safari/537.36"
)
TIMEOUT = 30
LOOKBACK_DAYS = 7

FULLTEXT_FIELD = "vyhledavaciSekce[3].vyhledavaciPodminka[0].vyhledavaciPodminkaHodnota[0].HodnotaText"
DATE_FROM_FIELD = "vyhledavaciSekce[1].vyhledavaciPodminka[0].vyhledavaciPodminkaHodnota[0].HodnotaDatumACasOd"
DATE_TO_FIELD = "vyhledavaciSekce[1].vyhledavaciPodminka[0].vyhledavaciPodminkaHodnota[0].HodnotaDatumACasDo"
DPH_PHRASE = "daň z přidané hodnoty"


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

    landing = session.get(BASE_URL, timeout=TIMEOUT)
    landing.raise_for_status()
    soup = BeautifulSoup(landing.text, "lxml")
    form = soup.find("form", id="findform")
    if form is None:
        log.warning("NSS landing page has no findform — site layout changed.")
        return

    overrides = {
        FULLTEXT_FIELD: DPH_PHRASE,
        DATE_FROM_FIELD: date_from,
        DATE_TO_FIELD: date_to,
    }
    form_data = _collect_form_fields(form, overrides)

    resp = session.post(
        SUBMIT_URL,
        data=form_data,
        headers={"Referer": BASE_URL},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    yield from _parse_results(BeautifulSoup(resp.text, "lxml"))


def _collect_form_fields(form: Tag, overrides: dict[str, str]) -> list[tuple[str, str]]:
    """Harvest all form inputs to replay the POST. Respect radio/checkbox semantics."""
    data: list[tuple[str, str]] = []
    applied: set[str] = set()
    for el in form.find_all(["input", "textarea", "select"]):
        name = el.get("name")
        if not name:
            continue
        t = (el.get("type") or el.name).lower()
        if t in ("submit", "button", "image", "reset", "file"):
            continue
        if name in overrides:
            data.append((name, overrides[name]))
            applied.add(name)
            continue
        if t == "radio":
            if el.has_attr("checked"):
                data.append((name, el.get("value", "")))
        elif t == "checkbox":
            if el.has_attr("checked"):
                data.append((name, el.get("value") or "on"))
        elif el.name == "select":
            selected = el.find("option", selected=True) or el.find("option")
            data.append((name, selected.get("value", "") if selected else ""))
        else:
            data.append((name, el.get("value") or ""))

    missing = set(overrides) - applied
    if missing:
        log.warning("NSS form is missing expected fields: %s", sorted(missing))
    return data


SPIS_ZN_RE = re.compile(r"\b\d+\s*Afs\s*\d+\s*/\s*\d{4}(?:\s*-\s*\d+)?\b", re.IGNORECASE)
DATE_CELL_RE = re.compile(r"^\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")


def _parse_results(soup: BeautifulSoup) -> Iterable[ScrapedItem]:
    # Result table has columns: # | Datum | Číslo jednací | Soud (senát) |
    # Druh dokumentu | Výrok | Účastníci | Právní věta | Kasační/ústavní | Možnosti.
    table = soup.find("table", id="tresults")
    if table is None:
        log.info("NSS results table not found (zero results or redesign).")
        return

    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        # Data rows have columns: # | (empty) | Datum | Čj. | Soud | Druh | Výrok | Účastníci | ...
        if len(cells) < 4:
            continue  # header / spacer row
        date_txt = cells[2].get_text(" ", strip=True)
        spis_txt = cells[3].get_text(" ", strip=True)

        m = SPIS_ZN_RE.search(spis_txt)
        if not m:
            continue  # non-Afs agenda (As, Ads, ...) — skip

        spis_zn = _normalize_spis_zn(m.group(0))
        parties = cells[7].get_text(" ", strip=True) if len(cells) > 7 else ""
        vyrok = cells[6].get_text(" ", strip=True) if len(cells) > 6 else ""

        detail = tr.find("a", href=re.compile(r"/DokumentDetail/Index/"))
        url = urljoin(BASE_URL, detail.get("href", "")) if detail else BASE_URL

        title_parts = [spis_zn]
        if vyrok:
            title_parts.append(vyrok)
        if parties:
            title_parts.append(parties)
        title = " — ".join(title_parts)[:250]

        yield ScrapedItem(
            source="NSS",
            item_key=spis_zn,
            title=title,
            url=url,
            item_date=_parse_date(date_txt) or "",
        )


def _normalize_spis_zn(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip())


def _parse_date(text: str) -> str | None:
    m = DATE_CELL_RE.match(text)
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"
