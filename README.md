# Club Connections

Which current players in Europe's **big four leagues** — Premier League, Bundesliga, Serie A, La Liga — have been part of each club, **first team or academy**, with stint years.

Live: https://jorgequijano.github.io/pl-connections/

## How it works

- **Rosters**: first-team squads (26/27 season) from [Transfermarkt](https://www.transfermarkt.com) squad pages (neutral `/-/kader/verein/{id}` URLs).
- **Per-player history**: youth affiliations ("Youth clubs" box) + full transfer history (incl. youth-level moves) from the profile page and Transfermarkt's internal `ceapi/transferHistory` JSON endpoint.
- **Pipeline (two phases)**:
  1. `crawl` — fetch squads + player history into a resumable raw cache (`data/raw/`), write per-league club registries (`data/leagues/{eng,deu,ita,esp}.json`) and squad membership (`data/membership.json`)
  2. `assemble` — rebuild the final dataset from cache, normalizing every club mention against a full 78-club registry (order-independent cross-league matching)
- **Output**: one static JSON (`data/pl-connections.json`); the site is a dependency-free static page (league tabs, ranking chart, searchable club drill-down).

## Try it locally

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

## Refresh the data

```bash
python3 -m venv .venv && .venv/bin/pip install requests beautifulsoup4

# fetch (resumable; sleeps ~1.3s between requests, auto-backoff on 403/429)
.venv/bin/python scripts/crawl.py crawl --leagues eng,deu,ita,esp
.venv/bin/python scripts/crawl.py crawl --leagues ita --limit 3   # smoke test

# rebuild the dataset from cache (no network)
.venv/bin/python scripts/crawl.py assemble
```

A GitHub Action (`.github/workflows/refresh.yml`) re-crawls monthly (and on manual dispatch), committing the dataset when it changes.

## Data schema

```jsonc
{
  "meta": {
    "season": "26/27",
    "leagues": [{ "key": "eng", "name": "Premier League",
                  "clubs": [{ "id": 631, "name": "Chelsea", "squadSize": 28 }] }]
  },
  "players": [{
    "id": "357662", "name": "Declan Rice", "position": "Defensive Midfield", "group": "MF",
    "league": "eng", "club": { "id": 11, "name": "Arsenal" },
    "involvements": [
      { "club": "Chelsea", "role": "academy", "years": "2006-2013" },
      { "club": "West Ham United", "role": "senior", ... },
      { "club": "Arsenal", "role": "senior", ... }
    ]
  }]
}
```

`role` is `senior`, `academy` (youth-club affiliation / youth-level move only), or `both`. Youth-level rows collapse onto their parent club via an alias + registry matcher.

## Caveats

- **Personal/hobby use.** Transfermarkt data is scraped via unofficial endpoints — cache the output, don't hammer the site, don't build a commercial product on it without a licensed source. Transfermarkt rate-limits aggressively; the crawler backs off and resumes from cache, and runs are best spread out.
- Rosters are snapshot-at-crawl-time; re-run after transfer windows.
- Roles are inferred from Transfermarkt club naming (youth markers like `U18`/`Yth.`/`II`). Edge cases exist — treat counts as approximate.
