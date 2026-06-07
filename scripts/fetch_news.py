#!/usr/bin/env python3
"""Fetch recent real-world headlines to ground the daily Current-Affairs questions.

Standard-library only (urllib + xml.etree) so it runs in CI with no install step.
Pulls a few reputable, UPSC-relevant RSS feeds (government + national + world),
de-duplicates, keeps the most recent items, and returns lightweight headline dicts.

Every network call is defensive: a failing or slow feed is skipped, never fatal.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

logger = logging.getLogger("fetch_news")

# (label, url). Reputable, UPSC-relevant feeds. Failing/slow feeds are skipped.
FEEDS: list[tuple[str, str]] = [
    ("The Hindu - National", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("The Hindu - International", "https://www.thehindu.com/news/international/feeder/default.rss"),
    ("The Hindu - Business", "https://www.thehindu.com/business/feeder/default.rss"),
    (
        "Affairs/Policy (Google News)",
        "https://news.google.com/rss/search?q=India+(policy+OR+economy+OR+%22supreme+court%22+"
        "OR+parliament+OR+RBI+OR+%22international+relations%22+OR+scheme)+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
    ),
    ("Google News India", "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"),
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_USER_AGENT = "daily-gk-upsc/1.0 (+https://github.com/sidhartha-patra/daily-gk-upsc)"


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return _WS_RE.sub(" ", text).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _fetch_feed(label: str, url: str, timeout: int = 15) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    root = ET.fromstring(raw)
    items: list[dict] = []
    # RSS 2.0: channel/item ; Atom: entry
    nodes = root.findall(".//item")
    if not nodes:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        nodes = root.findall(".//a:entry", ns)
    for node in nodes:
        title = node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title")
        desc = node.findtext("description") or node.findtext("{http://www.w3.org/2005/Atom}summary")
        link = node.findtext("link") or ""
        pub = node.findtext("pubDate") or node.findtext("{http://www.w3.org/2005/Atom}updated")
        title = _clean(title)
        if not title:
            continue
        items.append(
            {
                "title": title,
                "summary": _clean(desc)[:280],
                "link": link.strip(),
                "source": label,
                "published": _parse_date(pub),
            }
        )
    return items


def fetch_headlines(max_items: int = 24, days: int = 4) -> list[dict]:
    """Return up to *max_items* recent, de-duplicated headlines across all feeds."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    collected: list[dict] = []
    seen: set[str] = set()
    for label, url in FEEDS:
        try:
            items = _fetch_feed(label, url)
            logger.info("news: %s -> %d items", label, len(items))
        except Exception as exc:  # noqa: BLE001
            logger.warning("news: %s failed: %s", label, exc)
            continue
        for it in items:
            key = re.sub(r"[^a-z0-9]+", " ", it["title"].lower()).strip()[:120]
            if key in seen:
                continue
            if it["published"] and it["published"] < cutoff:
                continue
            seen.add(key)
            collected.append(it)

    collected.sort(key=lambda x: x["published"] or cutoff, reverse=True)
    return collected[:max_items]


def headlines_as_context(headlines: list[dict], limit: int = 18) -> str:
    """Render headlines as a compact bullet list for an LLM prompt."""
    lines = []
    for h in headlines[:limit]:
        when = h["published"].strftime("%d %b") if h.get("published") else ""
        extra = f" — {h['summary']}" if h.get("summary") else ""
        lines.append(f"- ({h['source']}{', ' + when if when else ''}) {h['title']}{extra}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hs = fetch_headlines()
    print(f"\nFetched {len(hs)} headlines:\n")
    for h in hs:
        when = h["published"].strftime("%Y-%m-%d") if h.get("published") else "?"
        print(f"[{when}] ({h['source']}) {h['title']}")
