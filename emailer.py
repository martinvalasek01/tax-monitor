"""Send the daily digest via Gmail SMTP."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Sequence

from scrapers.base import ScrapedItem

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_digest(recipient: str, items: Sequence[ScrapedItem], run_date_cz: str) -> None:
    user = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = recipient
    msg["Subject"] = _build_subject(items, run_date_cz)
    msg.set_content(_build_plain(items, run_date_cz))
    msg.add_alternative(_build_html(items, run_date_cz), subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=60) as smtp:
        smtp.login(user, app_password)
        smtp.send_message(msg)
    log.info("Digest sent to %s (%d items)", recipient, len(items))


def _build_subject(items: Sequence[ScrapedItem], run_date_cz: str) -> str:
    if not items:
        return f"[tax-monitor] {run_date_cz} — žádné nové DPH novinky"
    return f"[tax-monitor] {run_date_cz} — {len(items)} nových DPH položek"


def _build_plain(items: Sequence[ScrapedItem], run_date_cz: str) -> str:
    if not items:
        return "Žádné nové DPH novinky za posledních 24 hodin.\n"

    lines = [f"DPH novinky — {run_date_cz}", "=" * 50, ""]
    by_source: dict[str, list[ScrapedItem]] = {}
    for it in items:
        by_source.setdefault(it.source, []).append(it)

    for source, its in by_source.items():
        lines.append(f"## {source} ({len(its)})")
        lines.append("")
        for it in its:
            date = it.item_date or "—"
            lines.append(f"• {date} — {it.title}")
            lines.append(f"  {it.url}")
        lines.append("")
    return "\n".join(lines)


def _build_html(items: Sequence[ScrapedItem], run_date_cz: str) -> str:
    if not items:
        return "<p>Žádné nové DPH novinky za posledních 24 hodin.</p>"

    by_source: dict[str, list[ScrapedItem]] = {}
    for it in items:
        by_source.setdefault(it.source, []).append(it)

    parts = [
        "<html><body style=\"font-family: -apple-system, Segoe UI, sans-serif; font-size:14px\">",
        f"<h2>DPH novinky — {run_date_cz}</h2>",
    ]
    for source, its in by_source.items():
        parts.append(f"<h3>{_esc(source)} ({len(its)})</h3>")
        parts.append("<ul>")
        for it in its:
            date = _esc(it.item_date or "—")
            parts.append(
                f"<li><strong>{date}</strong> — "
                f"<a href=\"{_esc(it.url)}\">{_esc(it.title)}</a></li>"
            )
        parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace("\"", "&quot;")
    )
