"""Shared data model for all scrapers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScrapedItem:
    source: str          # e.g. "NSS", "GFŘ", "EUR-Lex"
    item_key: str        # stable unique identifier within source (spis. zn., URL slug, CELEX)
    title: str           # human-readable název věci
    url: str             # direct link to document
    item_date: str       # publication/decision date, best-effort YYYY-MM-DD or free text

    def to_email_row(self) -> str:
        date = self.item_date or "—"
        return f"[{self.source}] {date} — {self.title}\n    {self.url}"
