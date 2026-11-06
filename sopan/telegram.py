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
