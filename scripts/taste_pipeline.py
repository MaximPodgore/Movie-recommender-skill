#!/usr/bin/env python3
"""Import normalized snapshots, enrich films with TMDB, and build an evidence-based taste profile."""
from __future__ import annotations

import argparse, json, os, re, sqlite3, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Codex" / "letterboxd-recommender"
DB_PATH = DATA_DIR / "taste.sqlite"

MOVEMENTS = {
    "French New Wave": {"directors": {"jean-luc godard", "agnès varda", "françois truffaut", "eric rohmer", "jacques rivette", "claude chabrol", "alain resnais", "jacques demy"}, "countries": {"FR"}, "years": (1958, 1969)},
    "Italian Neorealism": {"directors": {"vittorio de sica", "roberto rossellini", "luchino visconti"}, "countries": {"IT"}, "years": (1943, 1955)},
    "New Hollywood": {"directors": {"robert altman", "francis ford coppola", "martin scorsese", "brian de palma", "peter bogdanovich", "hal ashby"}, "countries": {"US"}, "years": (1967, 1980)},
    "Taiwan New Wave": {"directors": {"hou hsiao-hsien", "edward yang", "tsai ming-liang"}, "countries": {"TW"}, "years": (1982, 2000)},
}
ADJACENCIES = {"French New Wave": ["Left Bank cinema", "Czechoslovak New Wave", "New German Cinema", "Taiwan New Wave"], "Italian Neorealism": ["French New Wave", "Iranian New Wave", "British social realism"], "New Hollywood": ["1970s American paranoia cinema", "American independent cinema", "revisionist western"], "Taiwan New Wave": ["slow cinema", "Hong Kong New Wave", "Korean New Wave"]}

def now() -> str: return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def clean(value: object) -> str: return str(value or "").strip()
def film_key(title: str, year: object = "") -> str: return f"{re.sub(r'[^a-z0-9]+', ' ', clean(title).lower()).strip()}|{clean(year)}"

def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True); con = sqlite3.connect(DB_PATH); con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS ingest_runs (run_id INTEGER PRIMARY KEY, source_key TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, coverage_json TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS taste_events (event_id INTEGER PRIMARY KEY, person TEXT NOT NULL, film_key TEXT NOT NULL, kind TEXT NOT NULL, rating REAL, occurred_at TEXT, source_key TEXT NOT NULL, run_id INTEGER, UNIQUE(person, film_key, kind, source_key));
    CREATE TABLE IF NOT EXISTS film_metadata (film_key TEXT PRIMARY KEY, tmdb_id INTEGER, match_confidence REAL, payload_json TEXT NOT NULL, enriched_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS film_features (film_key TEXT NOT NULL, feature_type TEXT NOT NULL, feature_value TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(film_key, feature_type, feature_value));
    CREATE TABLE IF NOT EXISTS taste_profiles (person TEXT PRIMARY KEY, profile_json TEXT NOT NULL, built_at TEXT NOT NULL);
    """)
    return con

def ensure_film(con: sqlite3.Connection, title: str, year: str) -> str:
    key = film_key(title, year); con.execute("INSERT OR IGNORE INTO films VALUES (?, ?, ?, ?)", (key, clean(title), clean(year), now())); return key

def migrate_legacy(con: sqlite3.Connection) -> None:
    for row in con.execute("SELECT film_key, kind, rating, watched_at, source_key FROM user_signals"):
        con.execute("INSERT OR IGNORE INTO taste_events(person,film_key,kind,rating,occurred_at,source_key) VALUES ('you',?,?,?,?,?)", (row["film_key"], row["kind"], row["rating"], row["watched_at"], row["source_key"]))
    for row in con.execute("SELECT friend_name, film_key, kind, rating, source_key FROM friend_signals"):
        con.execute("INSERT OR IGNORE INTO taste_events(person,film_key,kind,rating,source_key) VALUES (?,?,?,?,?)", (row["friend_name"], row["film_key"], row["kind"], row["rating"], row["source_key"]))

def import_snapshot(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.snapshot).read_text(encoding="utf-8")); person = clean(args.person); source = f"public:{clean(payload.get('username')).lower()}"
    if not person or not payload.get("username"): raise SystemExit("Snapshot must include username and --person.")
    con = db(); migrate_legacy(con); coverage = payload.get("coverage", {})
    cur = con.execute("INSERT INTO ingest_runs(source_key,method,status,coverage_json,started_at) VALUES (?,?,?,?,?)", (source, "public_snapshot", "running", json.dumps(coverage), now())); run_id = cur.lastrowid
    con.execute("DELETE FROM taste_events WHERE person=? AND source_key=?", (person, source)); counts = defaultdict(int)
    for row in payload.get("ratings", []):
        title = clean(row.get("title")); rating = row.get("rating")
        if not title or rating is None: continue
        key = ensure_film(con, title, clean(row.get("year"))); con.execute("INSERT OR REPLACE INTO taste_events(person,film_key,kind,rating,source_key,run_id) VALUES (?,?, 'rated',?,?,?)", (person, key, float(rating), source, run_id)); counts["ratings"] += 1
    for row in payload.get("watchlist", []):
        title = clean(row.get("title"));
        if not title: continue
        key = ensure_film(con, title, clean(row.get("year"))); con.execute("INSERT OR REPLACE INTO taste_events(person,film_key,kind,source_key,run_id) VALUES (?,?,'watchlist',?,?)", (person, key, source, run_id)); counts["watchlist"] += 1
    complete = all(v.get("complete", False) for v in coverage.values()) if coverage else False
    con.execute("UPDATE ingest_runs SET status=?,completed_at=? WHERE run_id=?", ("complete" if complete else "partial", now(), run_id)); con.commit(); con.close(); print(json.dumps({"person": person, "source": source, "status": "complete" if complete else "partial", "imported": counts}, indent=2))

def tmdb_request(path: str, params: dict) -> dict:
    token, key = os.getenv("TMDB_READ_ACCESS_TOKEN"), os.getenv("TMDB_API_KEY"); headers = {"Accept": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    elif key: params["api_key"] = key
    else: raise SystemExit("Set TMDB_API_KEY or TMDB_READ_ACCESS_TOKEN before enriching films.")
    with urlopen(Request(f"https://api.themoviedb.org/3{path}?{urlencode(params)}", headers=headers), timeout=25) as response: return json.loads(response.read())

def movement_features(payload: dict, directors: list[str]) -> list[str]:
    year = int(payload.get("release_date", "0000")[:4] or 0); countries = {c.get("iso_3166_1") for c in payload.get("production_countries", [])}
    names = {name.lower() for name in directors}; result = []
    for movement, rule in MOVEMENTS.items():
        if names & rule["directors"] or (countries & rule["countries"] and rule["years"][0] <= year <= rule["years"][1]): result.append(movement)
    return result

def enrich(args: argparse.Namespace) -> None:
    con = db(); migrate_legacy(con)
    rows = con.execute("""
        SELECT f.film_key,f.title,f.year
        FROM films f JOIN taste_events e USING(film_key)
        LEFT JOIN film_metadata m USING(film_key)
        WHERE m.film_key IS NULL AND e.person=? AND (? IS NULL OR lower(f.title)=lower(?))
        GROUP BY f.film_key
        ORDER BY MAX(CASE WHEN e.kind='rated' THEN ABS(e.rating-2.5) WHEN e.kind='liked' THEN 1.5 ELSE 0 END) DESC,
                 MAX(CASE WHEN e.kind='watchlist' THEN 1 ELSE 0 END) DESC
        LIMIT ?
    """, (args.person, args.title, args.title, args.limit)).fetchall(); count = unmatched = 0
    for row in rows:
        search_params = {"query": row["title"], "include_adult": "false"}
        if row["year"]: search_params["year"] = row["year"]
        search = tmdb_request("/search/movie", search_params); results = search.get("results", [])
        if not results:
            con.execute("INSERT OR REPLACE INTO film_metadata VALUES (?,?,?,?,?)", (row["film_key"], None, 0.0, json.dumps({"unmatched": True}), now()))
            con.commit(); unmatched += 1; continue
        candidate = results[0]; payload = tmdb_request(f"/movie/{candidate['id']}", {"append_to_response": "credits,keywords,external_ids"}); directors = [c["name"] for c in payload.get("credits", {}).get("crew", []) if c.get("job") == "Director"]
        features = [("director", d) for d in directors] + [("genre", g["name"]) for g in payload.get("genres", [])] + [("country", c["iso_3166_1"]) for c in payload.get("production_countries", [])] + [("keyword", k["name"]) for k in payload.get("keywords", {}).get("keywords", [])] + [("era", f"{int(payload.get('release_date','0000')[:4] or 0)//10*10}s")] + [("movement", m) for m in movement_features(payload, directors)]
        con.execute("INSERT OR REPLACE INTO film_metadata VALUES (?,?,?,?,?)", (row["film_key"], candidate["id"], 1.0 if clean(payload.get("title")).lower() == row["title"].lower() else .7, json.dumps(payload), now())); con.execute("DELETE FROM film_features WHERE film_key=?", (row["film_key"],))
        con.executemany("INSERT OR IGNORE INTO film_features VALUES (?,?,?, 'tmdb')", [(row["film_key"], t, v) for t,v in features if v]); con.commit(); count += 1; time.sleep(.25)
    con.close(); print(json.dumps({"enriched": count, "unmatched": unmatched, "batch_limit": args.limit}))

def build_profile(args: argparse.Namespace) -> None:
    con = db(); migrate_legacy(con); weights, evidence = defaultdict(float), defaultdict(int)
    rows = con.execute("SELECT e.kind,e.rating,ff.feature_type,ff.feature_value FROM taste_events e JOIN film_features ff USING(film_key) WHERE e.person=?", (args.person,))
    for row in rows:
        weight = (float(row["rating"]) - 2.5) if row["kind"] == "rated" and row["rating"] is not None else (1.5 if row["kind"] == "liked" else (.35 if row["kind"] == "watchlist" else 0))
        weights[(row["feature_type"], row["feature_value"])] += weight; evidence[(row["feature_type"], row["feature_value"])] += 1
    positive = sorted(({"type":t,"value":v,"weight":round(w,2),"films":evidence[(t,v)]} for (t,v),w in weights.items() if w > 0), key=lambda x:(-x["weight"],-x["films"]))[:40]
    negative = sorted(({"type":t,"value":v,"weight":round(w,2),"films":evidence[(t,v)]} for (t,v),w in weights.items() if w < 0), key=lambda x:x["weight"])[:25]
    movements = [x["value"] for x in positive if x["type"] == "movement"]; adjacent = sorted({item for movement in movements for item in ADJACENCIES.get(movement, [])})
    profile = {"person":args.person,"method":"structured metadata affinity; not embedding similarity","top_affinities":positive,"negative_affinities":negative,"adjacent_unexplored_buckets":adjacent,"metadata_coverage":con.execute("SELECT count(*) FROM film_metadata").fetchone()[0]}
    con.execute("INSERT OR REPLACE INTO taste_profiles VALUES (?,?,?)", (args.person,json.dumps(profile),now())); con.commit(); con.close(); print(json.dumps(profile,indent=2))

def recommend(args: argparse.Namespace) -> None:
    """Rank trusted-friend and personal-watchlist candidates, then add metadata affinity."""
    con = db(); migrate_legacy(con)
    watched = {r[0] for r in con.execute("SELECT DISTINCT film_key FROM taste_events WHERE person='you' AND kind IN ('watched','rated','liked')")}
    trusted = {r[0] for r in con.execute("SELECT name FROM friends")}
    profile_row = con.execute("SELECT profile_json FROM taste_profiles WHERE person='you'").fetchone()
    profile = json.loads(profile_row[0]) if profile_row else {}
    affinities = {(x["type"], x["value"]): x["weight"] for x in profile.get("top_affinities", [])}
    dislikes = {(x["type"], x["value"]): x["weight"] for x in profile.get("negative_affinities", [])}
    candidates = defaultdict(lambda: {"score": 0.0, "reasons": [], "friends": set()})
    def add(key, points, reason, friend=None):
        if key in watched: return
        candidates[key]["score"] += points; candidates[key]["reasons"].append(reason)
        if friend: candidates[key]["friends"].add(friend)
    for row in con.execute("SELECT film_key FROM taste_events WHERE person='you' AND kind='watchlist'"):
        add(row["film_key"], 3, "on your watchlist")
    for row in con.execute("SELECT person,film_key,rating FROM taste_events WHERE kind='rated' AND rating >= 3.5 AND person != 'you'"):
        if row["person"] in trusted:
            add(row["film_key"], min(2, .75 + (row["rating"] - 3.5) * (1.25 / 1.5)), f"{row['person']} rated it {row['rating']:g}", row["person"])
    for row in con.execute("SELECT person,film_key FROM taste_events WHERE kind='watchlist' AND person != 'you'"):
        if row["person"] in trusted: add(row["film_key"], .75, f"on {row['person']}'s watchlist", row["person"])
    for key, item in candidates.items():
        for feature in con.execute("SELECT feature_type,feature_value FROM film_features WHERE film_key=?", (key,)):
            affinity = affinities.get((feature["feature_type"], feature["feature_value"]), 0)
            dislike = dislikes.get((feature["feature_type"], feature["feature_value"]), 0)
            if affinity: item["score"] += min(1.5, affinity * .08); item["reasons"].append(f"matches your {feature['feature_value']} affinity")
            if dislike: item["score"] += max(-1.5, dislike * .08)
    output = []
    for key, item in candidates.items():
        film = con.execute("SELECT title,year FROM films WHERE film_key=?", (key,)).fetchone()
        output.append({"title": film["title"], "year": film["year"], "score": round(item["score"], 2), "reasons": list(dict.fromkeys(item["reasons"]))[:5], "trusted_friends": sorted(item["friends"])})
    con.close(); output.sort(key=lambda x: (-x["score"], x["title"]))
    print(json.dumps({"recommendations": output[:args.limit], "metadata_note": "Metadata affinity is active after TMDB enrichment; otherwise this is evidence-based friend/watchlist ranking."}, indent=2))

def record_liked(args: argparse.Namespace) -> None:
    con = db(); migrate_legacy(con); key = ensure_film(con, args.title, args.year)
    con.execute("INSERT OR REPLACE INTO taste_events(person,film_key,kind,source_key,occurred_at) VALUES ('you',?,'liked','manual:conversation',?)", (key, now()))
    con.commit(); con.close(); print(json.dumps({"recorded": "liked", "title": args.title, "year": args.year}))

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__); subs=parser.add_subparsers(required=True)
    p=subs.add_parser("import-snapshot"); p.add_argument("--snapshot",required=True); p.add_argument("--person",required=True); p.set_defaults(func=import_snapshot)
    p=subs.add_parser("enrich"); p.add_argument("--limit",type=int,default=100); p.add_argument("--person",default="you"); p.add_argument("--title"); p.set_defaults(func=enrich)
    p=subs.add_parser("build-profile"); p.add_argument("--person",default="you"); p.set_defaults(func=build_profile)
    p=subs.add_parser("recommend"); p.add_argument("--limit",type=int,default=12); p.set_defaults(func=recommend)
    p=subs.add_parser("record-liked"); p.add_argument("--title",required=True); p.add_argument("--year",required=True); p.set_defaults(func=record_liked)
    args=parser.parse_args(); args.func(args)
if __name__ == "__main__": main()
