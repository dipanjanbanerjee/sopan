"""Fetching, link extraction, keyword filtering and deadline parsing."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

_repo = os.environ.get("GITHUB_REPOSITORY", "sopan")
USER_AGENT = f"Mozilla/5.0 (compatible; SopanBot/0.1; +https://github.com/{_repo})"
TIMEOUT = 30
_robots_cache: dict[str, RobotFileParser | None] = {}


@dataclass
class Item:
    id: str
    url: str
    title: str
    source: str
    context: str = ""
    deadline: str | None = None  # ISO date
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- fetching
def _robots_allows(url: str) -> bool:
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        rp = RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if r.status_code >= 400:
                _robots_cache[base] = None  # no robots.txt -> allowed
            else:
                rp.parse(r.text.splitlines())
                _robots_cache[base] = rp
        except requests.RequestException:
            _robots_cache[base] = None
    rp = _robots_cache[base]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def fetch(url: str, retries: int = 2) -> str:
    if not _robots_allows(url):
        raise PermissionError(f"robots.txt disallows {url}")
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------- extraction
def _context_text(a, title: str, own_key: str, base_url: str, pat: re.Pattern, max_len: int = 700) -> str:
    """Text of the closest enclosing block (the listing 'card') around a job link.

    Climbing stops before a block that contains a link to a *different* job ad,
    so one listing's text never leaks into its neighbour's.
    """
    ctx, node = title, a
    for _ in range(6):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            break
        t = node.get_text(" ", strip=True)
        if len(t) > max_len:
            break
        for x in node.find_all("a", href=True):
            m = pat.search(urldefrag(urljoin(base_url, x["href"]))[0])
            if m and m.group(0) != own_key:
                return re.sub(r"\s+", " ", ctx)
        ctx = t
    return re.sub(r"\s+", " ", ctx)


def extract_links(html: str, base_url: str, source: str, link_pattern: str | None = None) -> list[Item]:
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(link_pattern) if link_pattern else None
    base_host = urlparse(base_url).netloc
    items: dict[str, Item] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "javascript:", "tel:", "#")):
            continue
        url = urldefrag(urljoin(base_url, href))[0]
        if not url.startswith("http"):
            continue
        if pat:
            m = pat.search(url)
            if not m:
                continue
            key = urlparse(url).netloc + m.group(0)
        else:
            key = url
            if url.rstrip("/") == base_url.rstrip("/"):
                continue
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not title or len(title) < 4:
            continue
        ctx = _context_text(a, title, m.group(0), base_url, pat) if pat else title
        prev = items.get(key)
        if prev is None or len(title) > len(prev.title):
            items[key] = Item(id=key, url=url, title=title, source=source, context=ctx)
        elif len(ctx) > len(prev.context):
            prev.context = ctx
    # watch pages: ignore off-site links in the page chrome only if there are on-site ones
    out = list(items.values())
    if not pat and any(urlparse(i.url).netloc == base_host for i in out):
        out = [i for i in out if urlparse(i.url).netloc == base_host or len(i.title) > 15]
    return out


# ---------------------------------------------------------------- filtering
def compile_keywords(words: list[str]) -> re.Pattern:
    return re.compile("|".join(rf"\b(?:{w})" for w in words), re.IGNORECASE)


def matches(item: Item, match_any: re.Pattern | None, and_any: re.Pattern | None = None) -> bool:
    text = f"{item.title} {item.context}"
    if match_any is not None and not match_any.search(text):
        return False
    if and_any is not None and not and_any.search(text):
        return False
    return True


# ---------------------------------------------------------------- deadlines
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = (
    rf"(\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+\d{{4}})?"
    rf"|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?"
    rf"|\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{4}})"
)
_DEADLINE_RE = re.compile(
    rf"(?:closes?|closing\s+date|deadline|apply\s+by|applications?\s+(?:due|close)|until)\s*(?:on|:|-)?\s*{_DATE}",
    re.IGNORECASE,
)


def parse_deadline(text: str, today: date | None = None) -> str | None:
    today = today or date.today()
    m = _DEADLINE_RE.search(text)
    if not m:
        return None
    raw = m.group(1)
    has_year = bool(re.search(r"\d{4}", raw))
    try:
        d = dateparser.parse(raw, dayfirst=True, default=datetime(today.year, 1, 1)).date()
    except (ValueError, OverflowError):
        return None
    if not has_year and (today - d).days > 30:
        d = d.replace(year=d.year + 1)  # "Closes 11 Jan" seen in November -> next year
    return d.isoformat()
