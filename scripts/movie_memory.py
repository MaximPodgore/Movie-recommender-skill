#!/usr/bin/env python3
"""Local storage and shortlist generation for the Letterboxd Recommender skill."""
from __future__ import annotations

import argparse, csv, hashlib, json, os, re, sqlite3, time, zipfile
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Codex" / "letterboxd-recommender"
DB_PATH = DATA_DIR / "taste.sqlite"

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def clean(value): return str(value or "").strip()
def key(title, year=""): return f"{re.sub(r'[^a-z0-9]+', ' ', clean(title).lower()).strip()}|{clean(year)}"
def number(text):
    try: return float(text) if text != "" else None
    except ValueError: return None
def truthy(text): return clean(text).lower() in {"1", "true", "yes", "y", "watchlist", "queued"}
def value(row, *names):
    lowered = {clean(k).lower(): clean(v) for k, v in row.items()}
    return next((lowered[n.lower()] for n in names if lowered.get(n.lower())), "")

def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    db.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS films (film_key TEXT PRIMARY KEY, title TEXT NOT NULL, year TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sources (source_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, imported_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS user_signals (film_key TEXT NOT NULL REFERENCES films(film_key), kind TEXT NOT NULL, rating REAL, watched_at TEXT, tags TEXT NOT NULL DEFAULT '', source_key TEXT NOT NULL, PRIMARY KEY (film_key, kind, source_key));
    CREATE TABLE IF NOT EXISTS friends (name TEXT PRIMARY KEY, weight REAL NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS friend_signals (friend_name TEXT NOT NULL REFERENCES friends(name), film_key TEXT NOT NULL REFERENCES films(film_key), kind TEXT NOT NULL, rating REAL, tags TEXT NOT NULL DEFAULT '', source_key TEXT NOT NULL, PRIMARY KEY (friend_name, film_key, kind, source_key));
    CREATE TABLE IF NOT EXISTS feedback (film_key TEXT PRIMARY KEY REFERENCES films(film_key), action TEXT NOT NULL, rating REAL, updated_at TEXT NOT NULL);
    """)
    return db

def ensure_film(db, title, year):
    film_key = key(title, year)
    db.execute("INSERT OR IGNORE INTO films VALUES (?, ?, ?, ?)", (film_key, clean(title), clean(year), now()))
    return film_key

def read_csv_bytes(data):
    return list(csv.DictReader(data.decode("utf-8-sig", errors="replace").splitlines()))

def public_url(username, collection, page=1):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", username): raise SystemExit("The Letterboxd username contains unsupported characters.")
    suffix = f"page/{page}/" if page > 1 else ""
    return f"https://letterboxd.com/{username}/{collection}/{suffix}"

def fetch_public_page(username, collection, page):
    request = Request(public_url(username, collection, page), headers={"User-Agent": "Mozilla/5.0 (compatible; local-film-recommender/1.0)"})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            if error.code not in {403, 429} or attempt: raise SystemExit(f"Public profile request failed ({error.code}) at page {page}.")
        except URLError as error:
            if attempt: raise SystemExit(f"Public profile request failed at page {page}: {error.reason}")
        time.sleep(2)

def parse_public_cards(html):
    rows = []
    for block in re.findall(r'<li class="griditem">(.*?)</li>', html, flags=re.S):
        match = re.search(r'data-item-name="([^"]+)"', block)
        if not match: continue
        name = unescape(match.group(1)).strip()
        year_match = re.search(r"\s\((\d{4})\)$", name)
        year = year_match.group(1) if year_match else ""
        title = name[:year_match.start()].strip() if year_match else name
        rating_match = re.search(r'\brated-(\d+)\b', block)
        rows.append({"title": title, "year": year, "rating": int(rating_match.group(1)) / 2 if rating_match else None})
    return rows

def collect_public(username, collection):
    first = fetch_public_page(username, collection, 1)
    pages = [int(page) for page in re.findall(rf'/{re.escape(username)}/{collection}/page/(\d+)/', first)]
    last_page = min(max(pages, default=1), 20); rows = parse_public_cards(first)
    for page in range(2, last_page + 1):
        time.sleep(.5); rows.extend(parse_public_cards(fetch_public_page(username, collection, page)))
    return rows, last_page

def import_letterboxd(args):
    archive = Path(args.zip)
    if not archive.is_file(): raise SystemExit(f"Export not found: {archive}")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest(); source = "letterboxd:owner"
    with zipfile.ZipFile(archive) as z:
        files = {Path(n).name.lower(): n for n in z.namelist() if n.lower().endswith(".csv")}
        if not files: raise SystemExit("The ZIP does not contain CSV files.")
        rows = {name: read_csv_bytes(z.read(member)) for name, member in files.items()}
    db = connect(); db.execute("DELETE FROM user_signals WHERE source_key = ?", (source,)); count = Counter()
    for filename, kind in (("ratings.csv", "rated"), ("watched.csv", "watched"), ("watchlist.csv", "watchlist"), ("diary.csv", "diary")):
        for row in rows.get(filename, []):
            title, year = value(row, "Name", "Title", "Film"), value(row, "Year")
            if not title: continue
            film, rating = ensure_film(db, title, year), number(value(row, "Rating"))
            tags, date = value(row, "Tags"), value(row, "Date", "WatchedDate", "Watched Date")
            actual_kind = "rated" if rating is not None else ("watched" if kind == "diary" else kind)
            db.execute("INSERT OR REPLACE INTO user_signals VALUES (?, ?, ?, ?, ?, ?)", (film, actual_kind, rating, date, tags, source)); count[actual_kind] += 1
    db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?)", (source, digest, now())); db.commit(); db.close()
    print(json.dumps({"imported": dict(count), "database": str(DB_PATH)}, indent=2))

def import_friend(args):
    path, name = Path(args.file), clean(args.name)
    if not path.is_file() or not name: raise SystemExit("Provide an existing --file and a non-empty --name.")
    source = f"friend:{name.lower()}"; rows = read_csv_bytes(path.read_bytes()); db = connect()
    db.execute("DELETE FROM friend_signals WHERE source_key = ?", (source,)); db.execute("INSERT OR REPLACE INTO friends VALUES (?, ?, ?)", (name, args.weight, now())); count = Counter()
    for row in rows:
        title, year = value(row, "Title", "Name", "Film"), value(row, "Year")
        if not title: continue
        film, rating, tags = ensure_film(db, title, year), number(value(row, "Rating")), value(row, "Tags")
        on_watchlist = truthy(value(row, "Watchlist")) or value(row, "Type", "Kind").lower() == "watchlist"
        if rating is not None and rating >= 3.5:
            db.execute("INSERT OR REPLACE INTO friend_signals VALUES (?, ?, 'rated', ?, ?, ?)", (name, film, rating, tags, source)); count["endorsements"] += 1
        if on_watchlist:
            db.execute("INSERT OR REPLACE INTO friend_signals VALUES (?, ?, 'watchlist', NULL, ?, ?)", (name, film, tags, source)); count["watchlist"] += 1
    db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?)", (source, hashlib.sha256(path.read_bytes()).hexdigest(), now())); db.commit(); db.close()
    print(json.dumps({"friend": name, "imported": dict(count)}, indent=2))

def import_public_friend(args):
    name, username = clean(args.name), clean(args.username).lower()
    if not name or not username: raise SystemExit("Provide non-empty --name and --username values.")
    rated, rated_pages = collect_public(username, "films")
    watchlist, watchlist_pages = collect_public(username, "watchlist")
    source = f"public:{username}"; db = connect(); count = Counter()
    db.execute("DELETE FROM friend_signals WHERE source_key = ?", (source,))
    db.execute("INSERT INTO friends VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at", (name, 1, now()))
    for row in rated:
        if row["rating"] is None or row["rating"] < 3.5: continue
        film = ensure_film(db, row["title"], row["year"])
        db.execute("INSERT OR REPLACE INTO friend_signals VALUES (?, ?, 'rated', ?, '', ?)", (name, film, row["rating"], source)); count["endorsements"] += 1
    for row in watchlist:
        film = ensure_film(db, row["title"], row["year"])
        db.execute("INSERT OR REPLACE INTO friend_signals VALUES (?, ?, 'watchlist', NULL, '', ?)", (name, film, source)); count["watchlist"] += 1
    fingerprint = hashlib.sha256(json.dumps({"rated": rated, "watchlist": watchlist}, sort_keys=True).encode()).hexdigest()
    db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?)", (source, fingerprint, now())); db.commit(); db.close()
    print(json.dumps({"friend": name, "username": username, "rated_pages": rated_pages, "watchlist_pages": watchlist_pages, "imported": dict(count)}, indent=2))

def import_public_snapshot(args):
    path, name, username = Path(args.file), clean(args.name), clean(args.username).lower()
    if not path.is_file() or not name or not username: raise SystemExit("Provide an existing --file plus non-empty --name and --username values.")
    payload = json.loads(path.read_text(encoding="utf-8")); rated = payload.get("ratings", []); watchlist = payload.get("watchlist", [])
    if not isinstance(rated, list) or not isinstance(watchlist, list): raise SystemExit("Snapshot must contain ratings and watchlist arrays.")
    source = f"public:{username}"; db = connect(); count = Counter()
    db.execute("DELETE FROM friend_signals WHERE source_key = ?", (source,))
    db.execute("INSERT INTO friends VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at", (name, 1, now()))
    for row in rated:
        title, rating = clean(row.get("title")), number(clean(row.get("rating")))
        if not title or rating is None or rating < 3.5: continue
        film = ensure_film(db, title, clean(row.get("year")))
        db.execute("INSERT OR REPLACE INTO friend_signals VALUES (?, ?, 'rated', ?, '', ?)", (name, film, rating, source)); count["endorsements"] += 1
    for row in watchlist:
        title = clean(row.get("title"))
        if not title: continue
        film = ensure_film(db, title, clean(row.get("year")))
        db.execute("INSERT OR REPLACE INTO friend_signals VALUES (?, ?, 'watchlist', NULL, '', ?)", (name, film, source)); count["watchlist"] += 1
    db.execute("INSERT OR REPLACE INTO sources VALUES (?, ?, ?)", (source, hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), now())); db.commit(); db.close()
    print(json.dumps({"friend": name, "username": username, "partial_snapshot": True, "imported": dict(count)}, indent=2))

def add_friend(args):
    name = clean(args.name)
    if not name: raise SystemExit("Provide a non-empty --name.")
    db = connect()
    db.execute("INSERT INTO friends VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET weight=excluded.weight, updated_at=excluded.updated_at", (name, args.weight, now()))
    db.commit(); db.close()
    print(json.dumps({"trusted_friend": name, "weight": args.weight, "status": "registered; awaiting consented film data"}))

def profile(_):
    db = connect(); out = {"database": str(DB_PATH)}
    out["your_signals"] = {r["kind"]: r["count"] for r in db.execute("SELECT kind, count(*) count FROM user_signals GROUP BY kind")}
    out["trusted_friends"] = [{"name": r["name"], "weight": r["weight"]} for r in db.execute("SELECT name, weight FROM friends ORDER BY name")]
    out["highly_rated_recent"] = [dict(r) for r in db.execute("SELECT f.title, f.year, u.rating FROM user_signals u JOIN films f USING(film_key) WHERE u.kind='rated' AND u.rating >= 4 ORDER BY u.watched_at DESC, u.rating DESC LIMIT 12")]
    db.close(); print(json.dumps(out, indent=2))

def recommend(args):
    db = connect(); watched = {r[0] for r in db.execute("SELECT DISTINCT film_key FROM user_signals WHERE kind IN ('watched','rated')")}; candidates = {}
    def add(film, points, reason, friend=None):
        if film in watched: return
        item = candidates.setdefault(film, {"score": 0., "reasons": [], "friends": set()})
        item["score"] += points; item["reasons"].append(reason)
        if friend: item["friends"].add(friend)
    for r in db.execute("SELECT film_key FROM user_signals WHERE kind='watchlist'"): add(r["film_key"], 3, "on your watchlist")
    for r in db.execute("SELECT s.film_key, s.rating, s.friend_name, f.weight FROM friend_signals s JOIN friends f ON f.name=s.friend_name WHERE s.kind='rated'"):
        endorsement = min(2, .75 + max(0, r["rating"] - 3.5) * (1.25 / 1.5))
        add(r["film_key"], endorsement * r["weight"], f"{r['friend_name']} rated it {r['rating']:g}", r["friend_name"])
    for r in db.execute("SELECT s.film_key, s.friend_name, f.weight FROM friend_signals s JOIN friends f ON f.name=s.friend_name WHERE s.kind='watchlist'"):
        add(r["film_key"], .75 * r["weight"], f"on {r['friend_name']}'s watchlist", r["friend_name"])
    for film, item in list(candidates.items()):
        if len(item["friends"]) >= 2: add(film, 1.25, "multiple trusted friends point to it")
    for r in db.execute("SELECT film_key, action FROM feedback"):
        if r["film_key"] in candidates: add(r["film_key"], 1.5 if r["action"] == "liked" else -3, f"your prior feedback: {r['action']}")
    results = []
    for film, item in candidates.items():
        if item["score"] <= 0: continue
        row = db.execute("SELECT title, year FROM films WHERE film_key=?", (film,)).fetchone()
        results.append({"title": row["title"], "year": row["year"], "score": round(item["score"], 2), "reasons": item["reasons"], "trusted_friends": sorted(item["friends"])})
    db.close(); results.sort(key=lambda x: (-x["score"], x["title"].lower())); print(json.dumps({"recommendations": results[:args.limit], "count": len(results)}, indent=2))

def feedback(args):
    if args.action not in {"liked", "not_interested"}: raise SystemExit("--action must be liked or not_interested")
    db = connect(); film = ensure_film(db, args.title, args.year)
    db.execute("INSERT OR REPLACE INTO feedback VALUES (?, ?, ?, ?)", (film, args.action, args.rating, now())); db.commit(); db.close()
    print(json.dumps({"saved": args.action, "title": args.title, "year": args.year}))

def main():
    parser = argparse.ArgumentParser(description=__doc__); subs = parser.add_subparsers(required=True)
    p = subs.add_parser("import-letterboxd"); p.add_argument("--zip", required=True); p.set_defaults(func=import_letterboxd)
    p = subs.add_parser("import-friend"); p.add_argument("--name", required=True); p.add_argument("--file", required=True); p.add_argument("--weight", type=float, default=1); p.set_defaults(func=import_friend)
    p = subs.add_parser("import-public-friend"); p.add_argument("--name", required=True); p.add_argument("--username", required=True); p.set_defaults(func=import_public_friend)
    p = subs.add_parser("import-public-snapshot"); p.add_argument("--name", required=True); p.add_argument("--username", required=True); p.add_argument("--file", required=True); p.set_defaults(func=import_public_snapshot)
    p = subs.add_parser("add-friend"); p.add_argument("--name", required=True); p.add_argument("--weight", type=float, default=1); p.set_defaults(func=add_friend)
    p = subs.add_parser("profile"); p.set_defaults(func=profile)
    p = subs.add_parser("recommend"); p.add_argument("--limit", type=int, default=8); p.set_defaults(func=recommend)
    p = subs.add_parser("feedback"); p.add_argument("--title", required=True); p.add_argument("--year", default=""); p.add_argument("--action", required=True); p.add_argument("--rating", type=float); p.set_defaults(func=feedback)
    args = parser.parse_args(); args.func(args)

if __name__ == "__main__": main()
