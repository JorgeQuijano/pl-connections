# PL Connections

Which current **Premier League** players have been part of each club — **first team or academy** — with stint years.

Live demo: https://jorgequijano.github.io/pl-connections/

## How it works

- **Rosters**: each PL club's first-team squad for the current season, from [Transfermarkt](https://www.transfermarkt.com) squad pages.
- **Per-player history**: every player's youth affiliations ("Youth clubs" record) + full transfer history (incl. youth-level moves), from the profile page and Transfermarkt's internal `ceapi/transferHistory` JSON endpoint.
- **Output**: one static JSON (`data/pl-connections.json`) committed to the repo; the site is a dependency-free static page that filters it client-side.

## Try it locally

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

## Refresh the data

```bash
python3 -m venv .venv && .venv/bin/pip install requests beautifulsoup4
.venv/bin/python scripts/crawl.py                # all 20 PL clubs
.venv/bin/python scripts/crawl.py --clubs 631,11 # subset (spike/test)
.venv/bin/python scripts/crawl.py --limit 3      # smoke test per club
```

Raw per-player responses are cached in `data/raw/` (gitignored) so re-runs resume instead of re-fetching. The crawl sleeps ~1.1s between requests to stay polite.

A GitHub Action (`.github/workflows/refresh.yml`) re-crawls monthly (and on manual dispatch), committing the dataset when it changes.

## Data schema

```jsonc
{
  "meta": { "season": "26/27", "crawledAt": "...", "clubs": [{"id": 631, "name": "Chelsea", "squadSize": 30}] },
  "players": [{
    "id": "357662", "name": "Declan Rice", "position": "Defensive Midfield", "group": "MF",
    "club": { "id": 11, "name": "Arsenal" },
    "involvements": [
      { "club": "Chelsea", "role": "academy", "years": "2006-2013" },
      { "club": "West Ham United", "role": "academy", ... },
      { "club": "West Ham United", "role": "senior", ... },
      { "club": "Arsenal", "role": "senior", ... }
    ]
  }]
}
```

`role` is `senior` (played in the senior squad), `academy` (youth-club affiliation / youth-level move only), or `both`. Youth-level rows collapse onto their parent club via an alias table; unknown small clubs are kept under their raw name.

## Caveats

- **Personal/hobby use.** Transfermarkt data is scraped via unofficial endpoints — cache the output, don't hammer the site, and don't build a commercial product on it without a licensed source.
- Rosters are snapshot-at-crawl-time; re-run after transfer windows.
- Roles are inferred from Transfermarkt's own club naming (youth markers like `U18`/`Yth.`/`Youth`). Edge cases exist — treat counts as approximate.
