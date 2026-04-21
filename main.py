"""Entry point — scrape all sources, email new items, record state."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import db
from emailer import send_digest
from scrapers import fetch_eurlex, fetch_gfr, fetch_nss
from scrapers.base import ScrapedItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tax-monitor")

PRAGUE = ZoneInfo("Europe/Prague")
RECIPIENT = os.environ.get("RECIPIENT", "leitnerczechia@gmail.com")
FORCE = os.environ.get("TAX_MONITOR_FORCE") == "1"


def main() -> int:
    now_cz = datetime.now(PRAGUE)
    run_date = now_cz.strftime("%Y-%m-%d")

    if FORCE:
        log.info("TAX_MONITOR_FORCE=1 — bypassing weekend / already-ran / morning-window guards.")

    if not FORCE and now_cz.weekday() >= 5:
        log.info("Weekend in Prague (%s) — skipping.", now_cz.strftime("%A"))
        return 0

    # Idempotency: if we already emailed today, do nothing. GitHub Actions
    # runs two crons (DST-aware) and we want exactly one send per workday.
    with db.connect() as conn:
        if not FORCE and db.has_run_today(conn, run_date):
            log.info("Already ran for %s — skipping second fire.", run_date)
            return 0

        # We schedule two UTC crons (04:00 and 05:00) to cover both DST states,
        # but only the one that lands at 06:00 CZ should actually send. # Allow 06:00–10:59 to tolerate cron drift (GitHub Actions often delays 1–4 hours).
        if not FORCE and not (6 <= now_cz.hour <= 10):
            log.info("Outside morning window (CZ hour=%d) — skipping.", now_cz.hour)
            return 0

        log.info("Starting run for %s (CZ %s)", run_date, now_cz.isoformat())

        scraped: list[ScrapedItem] = []
        for name, fn in (("NSS", fetch_nss), ("GFŘ", fetch_gfr), ("EUR-Lex", fetch_eurlex)):
            items = fn()
            log.info("%s: %d items", name, len(items))
            scraped.extend(items)
        log.info("Total scraped: %d", len(scraped))

        new_items: list[ScrapedItem] = []
        for item in scraped:
            if db.already_seen(conn, item.source, item.item_key):
                continue
            new_items.append(item)
            db.mark_seen(conn, item.source, item.item_key, item.title, item.url, item.item_date)

        log.info("New items to send: %d", len(new_items))

        try:
            send_digest(RECIPIENT, new_items, run_date)
        except Exception:
            log.exception("Failed to send email — NOT marking run complete.")
            # Roll back mark_seen inserts so we retry next run.
            conn.rollback()
            return 1

        db.record_run(conn, run_date, len(new_items))

    return 0


if __name__ == "__main__":
    sys.exit(main())
