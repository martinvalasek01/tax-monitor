"""EUR-Lex scraper — Publications Office SPARQL endpoint.

The public EUR-Lex search (eur-lex.europa.eu) sits behind Amazon
CloudFront, which serves HTTP 202 + empty body + `x-amzn-waf-action:
challenge` to non-browser clients — feedparser silently sees 0
entries. The Publications Office SPARQL endpoint at
publications.europa.eu is not WAFed and exposes the same judgment
metadata via structured queries, so we filter for CJEU / General
Court judgments whose English title contains "value added tax".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

import requests

from .base import ScrapedItem

log = logging.getLogger(__name__)

SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
# Mozilla-style UA: the endpoint 403s the default requests UA.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) tax-monitor/1.0"
TIMEOUT = 60
LOOKBACK_DAYS = 60  # CJEU publishes VAT judgments every ~1–3 weeks; keep a safe margin.
CELEX_URL_TMPL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"

QUERY_TMPL = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX lang: <http://publications.europa.eu/resource/authority/language/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?celex ?date ?title WHERE {{
  ?work cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/JUDG> .
  ?work cdm:resource_legal_id_celex ?celex .
  ?work cdm:work_date_document ?date .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language lang:ENG .
  ?expr cdm:expression_title ?title .
  FILTER (CONTAINS(LCASE(STR(?title)), "value added tax"))
  FILTER (?date >= "{from_date}"^^xsd:date)
}}
ORDER BY DESC(?date)
LIMIT 100
"""


def fetch_eurlex() -> list[ScrapedItem]:
    try:
        return list(_fetch())
    except Exception as e:
        log.exception("EUR-Lex scraper failed: %s", e)
        return []


def _fetch() -> Iterable[ScrapedItem]:
    from_date = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    resp = requests.get(
        SPARQL_URL,
        params={"query": QUERY_TMPL.format(from_date=from_date)},
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": USER_AGENT,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    rows = resp.json().get("results", {}).get("bindings", [])
    for row in rows:
        celex = row["celex"]["value"]
        title = row["title"]["value"]
        raw_date = row["date"]["value"]  # ISO date, possibly with tz suffix

        # EUR-Lex titles use '#' to separate sections
        # (court+date, parties, proceeding type, subject keywords).
        # Keep the first two chunks — most informative, bounded length.
        parts = [p.strip() for p in title.split("#") if p.strip()]
        clean_title = " — ".join(parts[:2]) if parts else title

        yield ScrapedItem(
            source="EUR-Lex",
            item_key=celex,
            title=clean_title[:250],
            url=CELEX_URL_TMPL.format(celex=celex),
            item_date=raw_date[:10],
        )
