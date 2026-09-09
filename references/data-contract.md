# Local data contract

## Letterboxd export

Use the account-export ZIP downloaded from Letterboxd Settings. The importer reads `ratings.csv`, `watched.csv`, `watchlist.csv`, and `diary.csv` when present. It recognizes common `Name`/`Title`, `Year`, `Rating`, `Date`, and `Tags` headers. A film is matched locally by normalized title and year; a missing year is allowed but makes matching less certain.

The export is a snapshot. Importing a new export replaces prior rows from that source, so it is safe to refresh without duplicate entries.

## Trusted-friend pack

One CSV represents one consented friend. Use either format below. Ratings use Letterboxd's 0.5–5 scale. Only ratings of 3.5 or higher are endorsements.

Wide format:

```csv
Title,Year,Rating,Watchlist,Tags
The Handmaiden,2016,4.5,false,"thriller,romance"
Mikey and Nicky,1976,,true,"crime"
```

Long format:

```csv
Title,Year,Type,Rating,Tags
The Handmaiden,2016,rated,4.5,"thriller,romance"
Mikey and Nicky,1976,watchlist,,"crime"
```

`Title` (or `Name`) is required. `Year`, `Rating`, `Watchlist`, `Type`, and `Tags` are optional. The importer only retains a friend rating when it is at least 3.5; it retains watchlist entries independently.

## User-authorized public profiles

When the user explicitly names a Letterboxd username, the public collector saves the visible `Films` and `Watchlist` pages as a normalized JSON snapshot. It uses no API, account login, cookies, or private pages. Collection and import are separate operations. A snapshot includes page coverage and completion status, so an incomplete collection is never confused with a complete account history.

Public data can be incomplete because entries, ratings, or watchlists may be hidden. Treat the imported data as a current public snapshot, not as a complete account history.

If a public site temporarily blocks a paginated collector, a browser-derived starter snapshot may be imported instead. It is explicitly partial and is replaced by the next successful complete refresh for the same username.

## Local storage

The SQLite file is created at `%LOCALAPPDATA%\\Codex\\letterboxd-recommender\\taste.sqlite`. It stores titles, years, user signals, friend signals, feedback, source fingerprints, and import timestamps. It does not store source ZIPs, credentials, or cookies.
