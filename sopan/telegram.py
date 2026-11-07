"""Minimal Telegram Bot API sender (no extra library needed)."""
from __future__ import annotations

import html
import time
from datetime import date

import requests

LIMIT = 3800  # Telegram allows 4096 chars per message; keep a margin


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def format_item(it: dict, today: date | None = None) -> str:
    today = today or date.today()
    lines = [f"🎓 <b>{esc(it['title'])}</b>", f"🏛 {esc(it['source'])}"]
    if it.get("deadline"):
        days = (date.fromisoformat(it["deadline"]) - today).days
        when = date.fromisoformat(it["deadline"]).strftime("%d %b %Y")
        lines.append(f"⏳ Deadline: {when} ({days} days left)" if days >= 0 else f"⏳ Deadline: {when}")
    lines.append(f'🔗 <a href="{html.escape(it["url"])}">Details &amp; apply</a>')
    return "\n".join(lines)


def format_digest(items: list[dict], today: date, site: str | None, show: int = 5) -> str:
    """Morning message for days with nothing new, so the channel never goes silent."""
    open_now = [i for i in items if not i.get("deadline") or date.fromisoformat(i["deadline"]) >= today]
    soon = sorted((i for i in open_now if i.get("deadline")), key=lambda i: i["deadline"])[:show]
    lines = [f"☀️ <b>Sopan · {today:%d %b}</b>",
             f"No new openings since the last update. {len(open_now)} PhD openings are open right now."]
    if soon:
        lines.append("\n<b>Closing soonest</b>")
        for i in soon:
            days = (date.fromisoformat(i["deadline"]) - today).days
            when = "today" if days == 0 else "1 day" if days == 1 else f"{days} days"
            title = i["title"] if len(i["title"]) <= 90 else i["title"][:87].rsplit(" ", 1)[0] + "…"
            lines.append(f'⏳ {when} · <a href="{html.escape(i["url"])}">{esc(title)}</a>')
    if site:
        lines.append(f'\n🔗 <a href="{html.escape(site)}">See all openings</a>')
    return "\n".join(lines)


def format_roundup(items: list[dict], today: date, site: str | None) -> list[str]:
    """Everything open right now, by deadline: one compact line per opening."""
    open_now = [i for i in items if not i.get("deadline") or date.fromisoformat(i["deadline"]) >= today]
    open_now.sort(key=lambda i: i.get("deadline") or "9999")
    blocks = []
    for i in open_now:
        when = date.fromisoformat(i["deadline"]).strftime("%d %b") if i.get("deadline") else "Open"
        blocks.append(f'⏳ <b>{when}</b> · <a href="{html.escape(i["url"])}">{esc(i["title"])}</a>\n'
                      f'      <i>{esc(i["source"])}</i>')
    if site:
        blocks.append(f'🔗 <a href="{html.escape(site)}">Search, save and add deadlines to your calendar</a>')
    header = f"📚 <b>All {len(open_now)} PhD openings open right now</b> · {today:%d %b}\nSorted by deadline."
    return chunk(blocks, header)


def chunk(blocks: list[str], header: str = "") -> list[str]:
    msgs, cur = [], header
    for b in blocks:
        piece = ("\n\n" if cur else "") + b
        if len(cur) + len(piece) > LIMIT and cur:
            msgs.append(cur)
            cur = b
        else:
            cur += piece
    if cur:
        msgs.append(cur)
    return msgs


def send(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    for _ in range(5):
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 429:  # rate limited
            time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
            continue
        if not r.ok:
            raise RuntimeError(f"Telegram error {r.status_code}: {r.text[:300]}")
        time.sleep(3.1)  # stay under the channel limit of ~20 messages/minute
        return
    raise RuntimeError("Telegram kept rate-limiting; giving up")
