#!/usr/bin/env python3
"""Collect a public Letterboxd profile into a normalized JSON snapshot; never writes the taste database."""
from __future__ import annotations

import argparse, json, re, time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def page_url(username: str, collection: str, page: int) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", username): raise SystemExit("Unsupported username.")
    return f"https://letterboxd.com/{username}/{collection}/" + (f"page/{page}/" if page > 1 else "")

def fetch(username: str, collection: str, page: int) -> str:
    request = Request(page_url(username, collection, page), headers={"User-Agent": "Mozilla/5.0 (compatible; local-film-recommender/2.0)"})
    try:
        with urlopen(request, timeout=25) as response: return response.read().decode("utf-8", "replace")
    except (HTTPError, URLError) as error: raise RuntimeError(f"{collection} page {page}: {error}") from error

def parse_cards(html: str) -> list[dict]:
    rows = []
    for block in re.findall(r'<li class="griditem">(.*?)</li>', html, flags=re.S):
        match = re.search(r'data-item-name="([^"]+)"', block)
        if not match: continue
        display = unescape(match.group(1)).strip(); year_match = re.search(r"\s\((\d{4})\)$", display)
        rating_match = re.search(r'\brated-(\d+)\b', block)
        rows.append({"title": display[:year_match.start()].strip() if year_match else display, "year": year_match.group(1) if year_match else "", "rating": int(rating_match.group(1)) / 2 if rating_match else None})
    return rows

def collect(username: str, collection: str, max_pages: int, previous: dict | None = None) -> tuple[list[dict], dict]:
    previous = previous or {}; pages = {int(p) for p in previous.get("pages_collected", [])}
    available = previous.get("available_pages"); available = int(available) if available else None
    if not pages:
        first = fetch(username, collection, 1); pages.add(1); rows = parse_cards(first)
        discovered = [int(n) for n in re.findall(rf'/{re.escape(username)}/{collection}/page/(\d+)/', first)]
        available = max(discovered) if discovered else None
    else:
        rows = []
    if previous.get("blocked_at_page"): return rows, {**previous, "pages_collected": sorted(pages)}
    pending = ([page for page in range(1, available + 1) if page not in pages] if available else [max(pages) + 1])[:max_pages]
    for page in pending:
        if page == 1 and rows: continue
        if rows: time.sleep(1)
        try:
            rows.extend(parse_cards(fetch(username, collection, page))); pages.add(page)
        except RuntimeError as error:
            return rows, {"available_pages": available, "pages_collected": sorted(pages), "collected_pages": len(pages), "complete": False, "blocked_at_page": page, "last_error": str(error)}
    return rows, {"available_pages": available, "pages_collected": sorted(pages), "collected_pages": len(pages), "complete": bool(available and len(pages) == available)}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--username", required=True); parser.add_argument("--output", required=True); parser.add_argument("--max-pages", type=int, default=20); parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.max_pages < 1: raise SystemExit("--max-pages must be positive.")
    destination = Path(args.output); existing = json.loads(destination.read_text(encoding="utf-8")) if args.resume and destination.exists() else {}
    if existing and existing.get("username", "").lower() != args.username.lower(): raise SystemExit("Resume snapshot username does not match --username.")
    old_ratings = existing.get("coverage", {}).get("ratings", {}); old_watchlist = existing.get("coverage", {}).get("watchlist", {})
    if existing.get("schema", 1) < 3:
        for status in (old_ratings, old_watchlist):
            if status.get("available_pages") == status.get("collected_pages"): status["available_pages"] = None; status["complete"] = False
    ratings, ratings_status = collect(args.username, "films", args.max_pages, old_ratings)
    watchlist, watchlist_status = collect(args.username, "watchlist", args.max_pages, old_watchlist)
    def merge(old, new):
        merged = {(row["title"], row.get("year", "")): row for row in old}
        merged.update({(row["title"], row.get("year", "")): row for row in new}); return list(merged.values())
    snapshot = {"schema": 3, "username": args.username.lower(), "collected_at": datetime.now(timezone.utc).isoformat(), "ratings": merge(existing.get("ratings", []), ratings), "watchlist": merge(existing.get("watchlist", []), watchlist), "coverage": {"ratings": ratings_status, "watchlist": watchlist_status}}
    destination.parent.mkdir(parents=True, exist_ok=True); destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(destination), "ratings": len(ratings), "watchlist": len(watchlist), "coverage": snapshot["coverage"]}, indent=2))

if __name__ == "__main__": main()
