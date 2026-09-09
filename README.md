# Movie Recommender Skill — source

Version-controlled source for a local-first Letterboxd recommender. Personal exports, collected snapshots, SQLite data, and TMDB credentials stay outside this repository.

## Design

1. `scripts/collect_letterboxd_public.py` collects an authorized public Letterboxd profile into a JSON snapshot.
2. `scripts/taste_pipeline.py import-snapshot` imports a snapshot into local memory, retaining all ratings and explicit coverage status.
3. `scripts/taste_pipeline.py enrich` adds TMDB metadata locally. It reads `TMDB_READ_ACCESS_TOKEN` or `TMDB_API_KEY` from the environment; neither belongs in Git.
4. `build-profile` derives explainable affinities from directors, genres, countries, eras, keywords, and curated film movements. `recommend` combines those affinities with the user's watchlist and trusted-friend support.

## Local usage

```powershell
py scripts/collect_letterboxd_public.py --username examplefriend --output examplefriend.json
py scripts/taste_pipeline.py import-snapshot --person "Example Friend" --snapshot examplefriend.json
py scripts/taste_pipeline.py enrich --person you --limit 100
py scripts/taste_pipeline.py build-profile --person you
py scripts/taste_pipeline.py recommend --limit 12
```

The local database defaults to `%LOCALAPPDATA%\\Codex\\letterboxd-recommender\\taste.sqlite`.

## Boundaries

Collection is public-only and low-rate. It does not authenticate with Letterboxd or collect private data. The repository intentionally contains no user data, tokens, database files, or scraped snapshots.
