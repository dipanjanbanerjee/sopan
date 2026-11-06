"""Daily Sopan job: check sources, post new openings and reminders, update the web data.

Usage:
    python -m sopan.run --dry-run     # test locally: print what would be posted, change nothing
    python -m sopan.run               # real run (needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import yaml

from . import telegram as tg
from .core import Item, compile_keywords, extract_links, fetch, matches, parse_deadline

ROOT = Path(__file__).resolve().parent.parent
MAX_POSTS = 40           # openings posted per run; the rest are on the web page
REMIND_DAYS = 3          # "closing soon" reminder this many days before a deadline
KEEP_UNDATED_DAYS = 60   # undated openings stay on the web page this long


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def web_url(cfg: dict) -> str | None:
    if cfg.get("site", {}).get("web_url"):
        return cfg["site"]["web_url"]
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return None


def resolve(spec, profiles: dict):
    if spec is None:
        return None
    words = profiles[spec] if isinstance(spec, str) else spec
    return compile_keywords(words)


def scan(src: dict, profiles: dict, today: date, is_watch: bool, exclude=None) -> list[Item]:
    html = fetch(src["url"])
    found = extract_links(html, src["url"], src["name"], src.get("link_pattern"))
    if is_watch:
        return found
    m_any, a_any = resolve(src.get("match_any"), profiles), resolve(src.get("and_any"), profiles)
    kept = [i for i in found if matches(i, m_any, a_any) and not (exclude and exclude.search(i.title))]
    for i in kept:
        i.deadline = parse_deadline(i.context, today)
    print(f"  {src['name']}: {len(found)} listings, {len(kept)} match")
    if not found:
        print(f"  ⚠️  no listings found — check the URL or link_pattern for '{src['name']}'")
    return kept


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print instead of posting; change no files")
    ap.add_argument("--config", default=str(ROOT / "sources.yaml"))
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    profiles = cfg.get("keywords", {})
    exclude = resolve(cfg.get("exclude_titles") or None, profiles)
    today = date.today()

    state_path, data_path = ROOT / "state" / "seen.json", ROOT / "docs" / "data.json"
    state = load_json(state_path, {"initialized": [], "seen": {}})
    data = load_json(data_path, {"meta": {}, "items": []})
    web = {it["id"]: it for it in data.get("items", [])}

    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not args.dry_run and not (token and chat):
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (or use --dry-run).")
        return 2

    new_items: list[Item] = []
    watch_hits: list[Item] = []
    failures = 0
    all_sources = [(s, False) for s in cfg.get("sources", []) or []] + [(s, True) for s in cfg.get("watch", []) or []]

    for src, is_watch in all_sources:
        key = ("watch:" if is_watch else "") + src["name"]
        try:
            items = scan(src, profiles, today, is_watch, exclude)
        except Exception as e:  # one bad site must not stop the rest
            failures += 1
            print(f"  ❌ {src['name']}: {e}")
            continue
        first_time = key not in state["initialized"]
        for it in items:
            if args.dry_run:
                (watch_hits if is_watch else new_items).append(it)
                continue
            if it.id in state["seen"]:
                continue
            state["seen"][it.id] = today.isoformat()
            if not is_watch:
                web[it.id] = {"id": it.id, "url": it.url, "title": it.title, "source": it.source,
                              "deadline": it.deadline, "found": today.isoformat()}
            if not first_time:  # first scan of a source only records what's already there
                (watch_hits if is_watch else new_items).append(it)
        if first_time and not args.dry_run:
            state["initialized"].append(key)
            print(f"  ℹ️  first scan of '{src['name']}': {len(items)} existing listings recorded, not posted")
        time.sleep(2)  # be polite to the websites

    if all_sources and failures == len(all_sources):
        print("All sources failed.")
        return 1

    # deadline reminders
    reminders = []
    for it in web.values():
        if it.get("deadline") and not it.get("reminded"):
            left = (date.fromisoformat(it["deadline"]) - today).days
            if 0 <= left <= REMIND_DAYS:
                reminders.append(it)
                if not args.dry_run:
                    it["reminded"] = True

    # build messages
    site = web_url(cfg)
    messages: list[str] = []
    if new_items:
        shown = new_items[:MAX_POSTS]
        header = f"📌 <b>Sopan · {len(new_items)} new opening{'s' if len(new_items) > 1 else ''}</b> · {today:%d %b}"
        blocks = [tg.format_item(vars(i), today) for i in shown]
        if len(new_items) > MAX_POSTS:
            more = f"…and {len(new_items) - MAX_POSTS} more"
            blocks.append(f'{more} on <a href="{site}">the Sopan page</a>' if site else more)
        messages += tg.chunk(blocks, header)
    if reminders:
        blocks = [tg.format_item(r, today) for r in sorted(reminders, key=lambda r: r["deadline"])]
        messages += tg.chunk(blocks, "⏰ <b>Closing soon</b>")
    if watch_hits:
        blocks = [f"👀 <b>{tg.esc(w.source)}</b> has a new link:\n"
                  f'<a href="{tg.esc(w.url)}">{tg.esc(w.title)}</a>' for w in watch_hits]
        messages += tg.chunk(blocks, "🔔 <b>Watchlist update</b>")

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(new_items)} openings, {len(reminders)} reminders, "
              f"{len(watch_hits)} watch links (nothing posted or saved) ---\n")
        for m in messages:
            print(m, "\n" + "-" * 40)
        return 0

    for m in messages:
        tg.send(token, chat, m)
    print(f"Posted {len(messages)} message(s): {len(new_items)} new, {len(reminders)} reminders, {len(watch_hits)} watch.")

    # prune and save
    def keep(it):
        if exclude and exclude.search(it["title"]):
            return False
        if it.get("deadline"):
            return date.fromisoformat(it["deadline"]) >= today
        return date.fromisoformat(it["found"]) >= today - timedelta(days=KEEP_UNDATED_DAYS)

    items = sorted((i for i in web.values() if keep(i)), key=lambda i: i["found"], reverse=True)[:1000]
    seen = dict(sorted(state["seen"].items(), key=lambda kv: kv[1], reverse=True)[:20000])
    save_json(state_path, {"initialized": state["initialized"], "seen": seen})
    save_json(data_path, {"meta": {"updated": today.isoformat(),
                                   "telegram_url": cfg.get("site", {}).get("telegram_url")},
                          "items": items})
    return 0


if __name__ == "__main__":
    sys.exit(main())
