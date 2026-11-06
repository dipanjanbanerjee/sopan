"""Check candidate websites from the machine Sopan runs on.

    python -m sopan.probe URL [URL ...]

For each page prints the HTTP status, whether robots.txt allows Sopan, and the most
common shapes of links on the page (digits shown as #) with example link texts, which
is what you need to write a `link_pattern` in sources.yaml.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .core import USER_AGENT, _robots_allows


def shape(url: str) -> str:
    p = urlparse(url)
    parts = [re.sub(r"\d+", "#", s) for s in p.path.split("/") if s]
    parts = [s if len(s) <= 25 and "-" not in s[3:] else "*" for s in parts]  # slugs -> *
    q = "?" + re.sub(r"=[^&]*", "=…", p.query) if p.query else ""
    return f"{p.netloc}/{'/'.join(parts)}{q}"


def probe(url: str) -> None:
    print(f"\n=== {url}")
    try:
        allowed = _robots_allows(url)
    except Exception as e:  # noqa: BLE001
        allowed = f"? ({e})"
    print(f"robots.txt allows: {allowed}")
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}, timeout=30)
    except requests.RequestException as e:
        print(f"FETCH FAILED: {e}")
        return
    print(f"status: {r.status_code}  bytes: {len(r.text)}  final url: {r.url}")
    if not r.ok:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    counts, examples = Counter(), defaultdict(list)
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a["href"])
        if not href.startswith("http"):
            continue
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if len(text) < 12:
            continue
        s = shape(href)
        counts[s] += 1
        if len(examples[s]) < 2:
            examples[s].append(f"{text[:70]}  <{href[:110]}>")
    if not counts:
        print("no text links found (page may be built by JavaScript)")
    for s, n in counts.most_common(6):
        print(f"  {n:3d} × {s}")
        for ex in examples[s]:
            print(f"        e.g. {ex}")


if __name__ == "__main__":
    for u in sys.argv[1:]:
        probe(u)
