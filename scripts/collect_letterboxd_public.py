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

def collect(username: str, collection: str, max_pages: int) -> tuple[list[dict], dict]:
    first = fetch(username, collection, 1)
    available = max([int(n) for n in re.findall(rf'/{re.escape(username)}/{collection}/page/(\d+)/', first)] or [1])
    target = min(available, max_pages); rows = parse_cards(first)
    for page in range(2, target + 1):
        time.sleep(1); rows.extend(parse_cards(fetch(username, collection, page)))
    return rows, {"available_pages": available, "collected_pages": target, "complete": target == available}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--username", required=True); parser.add_argument("--output", required=True); parser.add_argument("--max-pages", type=int, default=20)
    args = parser.parse_args()
    if args.max_pages < 1: raise SystemExit("--max-pages must be positive.")
    ratings, ratings_status = collect(args.username, "films", args.max_pages)
    watchlist, watchlist_status = collect(args.username, "watchlist", args.max_pages)
    snapshot = {"schema": 1, "username": args.username.lower(), "collected_at": datetime.now(timezone.utc).isoformat(), "ratings": ratings, "watchlist": watchlist, "coverage": {"ratings": ratings_status, "watchlist": watchlist_status}}
    destination = Path(args.output); destination.parent.mkdir(parents=True, exist_ok=True); destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(destination), "ratings": len(ratings), "watchlist": len(watchlist), "coverage": snapshot["coverage"]}, indent=2))

if __name__ == "__main__": main()
