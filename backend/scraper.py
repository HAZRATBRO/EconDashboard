"""Scrape report listings from www.mospi.gov.in publication pages.

The scraper is deliberately structure-agnostic: it does not depend on specific
CSS classes (which change between site redesigns). It finds every link to a
downloadable document (PDF/XLS/XLSX/CSV/ZIP or a /sites/default/files/,
/uploads/ path), then walks up to the enclosing row (tr/li/article/div card)
to recover the title and a release date. Links to other listing pages
("innerpage", category pages) are returned separately for navigation.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from mospi_client import _session

ALLOWED_HOSTS = ("mospi.gov.in", "mospi.nic.in")
DOC_EXT = re.compile(r"\.(pdf|xlsx?|csv|zip|docx?)(\?|#|$)", re.I)
DOC_PATH = re.compile(r"/(sites/default/files|uploads|documents?)/", re.I)
ROW_TAGS = ("tr", "li", "article")

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTHS})[a-z]*[,.]?\s+(\d{{4}})\b", re.I), "d_mon_y"),
    (re.compile(rf"\b({_MONTHS})[a-z]*\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I), "mon_d_y"),
]

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 30 * 60


def is_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def parse_date(text: str) -> str | None:
    """Return the first date found in text as ISO yyyy-mm-dd."""
    for rx, kind in DATE_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        try:
            if kind == "dmy":
                d, mo, y = int(m[1]), int(m[2]), int(m[3])
            elif kind == "ymd":
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif kind == "d_mon_y":
                d, mo, y = int(m[1]), _month(m[2]), int(m[3])
            else:
                mo, d, y = _month(m[1]), int(m[2]), int(m[3])
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            continue
    return None


def _month(s: str) -> int:
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(s[:3].lower()) + 1


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _row_for(a: Tag) -> Tag:
    """Closest enclosing element that represents one listing item."""
    for parent in a.parents:
        if parent.name in ROW_TAGS:
            return parent
        if parent.name == "div" and len(parent.find_all("a", href=True)) <= 4 and len(_clean(parent.get_text(" "))) > 15:
            return parent
        if parent.name in ("body", "table", "ul", "ol"):
            break
    return a.parent or a


GENERIC_LINK_TEXT = re.compile(r"^(download|view|pdf|xlsx?|excel|click here|read more|english|hindi|file|\d+(\.\d+)?\s*(kb|mb))$", re.I)


def _title_for(a: Tag, row: Tag) -> str:
    text = _clean(a.get_text(" ")) or _clean(a.get("title", ""))
    if text and not GENERIC_LINK_TEXT.match(text) and len(text) > 6:
        return text
    # Prefer a heading or the longest text cell in the row.
    for sel in ("h1", "h2", "h3", "h4", "h5", "strong", "b", ".title", "td"):
        cands = [_clean(t.get_text(" ")) for t in row.select(sel)]
        cands = [c for c in cands if len(c) > 6 and not GENERIC_LINK_TEXT.match(c) and not parse_date(c) == c]
        if cands:
            return max(cands, key=len)[:300]
    row_text = _clean(row.get_text(" "))
    return row_text[:300] or text or a["href"].rsplit("/", 1)[-1]


def _file_type(href: str) -> str:
    m = DOC_EXT.search(href)
    return m.group(1).upper() if m else "LINK"


def parse_listing(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    page_title = _clean(soup.title.get_text()) if soup.title else ""
    heading = soup.find(["h1", "h2"])
    reports: dict[str, dict] = {}
    categories: dict[str, str] = {}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urljoin(page_url, href)
        if DOC_EXT.search(url) or DOC_PATH.search(url):
            row = _row_for(a)
            title = _title_for(a, row)
            key = url
            if key in reports:
                continue
            row_text = _clean(row.get_text(" "))
            reports[key] = {
                "title": title,
                "date": parse_date(row_text),
                "url": url,
                "file_type": _file_type(url),
                "context": row_text[:500] if row_text != title else "",
            }
        elif is_allowed(url) and re.search(r"(innerpage|publications-reports|publication_reports|press-release|cat=|category)", url, re.I):
            label = _clean(a.get_text(" "))
            if label and len(label) > 2 and url != page_url:
                categories.setdefault(url, label)

    # Group rows that share a title (e.g. English + Hindi PDFs of one report).
    merged: dict[tuple, dict] = {}
    for r in reports.values():
        k = (r["title"].lower(), r["date"])
        if k in merged:
            merged[k].setdefault("other_files", []).append({"url": r["url"], "file_type": r["file_type"]})
        else:
            merged[k] = r
    items = sorted(merged.values(), key=lambda r: r["date"] or "", reverse=True)

    next_page = None
    nxt = soup.find("a", attrs={"rel": "next"}) or soup.find("a", string=re.compile(r"^\s*(next|›|»|>)\s*", re.I))
    if nxt and nxt.get("href"):
        next_page = urljoin(page_url, nxt["href"])

    return {
        "page_url": page_url,
        "page_title": _clean(heading.get_text(" ")) if heading else page_title,
        "reports": items,
        "categories": [{"url": u, "label": l} for u, l in categories.items()][:200],
        "next_page": next_page,
    }


def fetch_listing(url: str) -> dict:
    if not is_allowed(url):
        raise ValueError("Only mospi.gov.in pages can be scraped")
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    r = _session.get(url, timeout=30)
    r.raise_for_status()
    result = parse_listing(r.text, r.url)
    result["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    _cache[url] = (time.time(), result)
    return result
