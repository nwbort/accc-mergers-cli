# accc-mergers-cli

A local command-line tool for querying the ACCC merger register. Search past
determinations, find similar cases by industry or issue, read the ACCC's
reasoning, and browse questionnaire questions — all from your terminal.

Data is pulled from the public
[`nwbort/accc-mergers`](https://github.com/nwbort/accc-mergers) repository and
indexed locally with SQLite FTS5.

## Installation

```bash
git clone https://github.com/nwbort/accc-mergers-cli
cd accc-mergers-cli
pip install -e .
```

Python 3.11+ is required. The only runtime dependencies are `typer`, `rich`,
and `httpx`.

## Quick start

```bash
# First run auto-syncs the local cache (~/.accc-mergers/).
mergers search "warehouse lease beverage"

# Full detail on a single merger.
mergers show MN-01016

# Browse by filter.
mergers list --outcome approved --industry beverage --year 2025

# Force-refresh the cache.
mergers sync --force
```

## Commands

| Command | Purpose |
|---|---|
| `mergers sync` | Download and index the latest data |
| `mergers sync --force` | Re-download and reindex even if the bundle hash matches |
| `mergers status` | Version, generation time, and age of the local cache |
| `mergers search <query>` | Full-text search of descriptions and determinations |
| `mergers show <id>` | Full detail on a single merger |
| `mergers timeline <id>` | Chronological event timeline for one merger, with durations |
| `mergers related <id>` | Mergers linked via the 'related merger' field (e.g. waiver refiled as a notification) |
| `mergers party <name>` | All mergers involving a given acquirer or target |
| `mergers list` | Browse with filters, no query required |
| `mergers questions [id]` | Browse questionnaire questions |
| `mergers industries` | Breakdown of activity by ANZSIC industry |
| `mergers stats` | Summary statistics |

Every command supports `--json` for machine-readable output.

## Filters

`search` and `list` share the same filter flags:

| Flag | Description |
|---|---|
| `--outcome` | `approved`, `denied`, `phase2`, `pending` |
| `--industry` | Partial ANZSIC name match (case-insensitive) |
| `--phase` | `1` or `2` |
| `--waiver` / `--no-waiver` | Waivers only / notifications only |
| `--year` | Notification year, e.g. `2025` |
| `--since` | Notified on or after this date (`YYYY-MM-DD`) |
| `--until` | Notified on or before this date (`YYYY-MM-DD`) |
| `--has-related` / `--no-related` | Only mergers that have (or do not have) a related merger |
| `--limit N` | Max results |

`search` also accepts `--regex` to interpret the query as a Python
regular expression instead of an FTS query. Useful for patterns FTS
can't express (e.g. `--regex "acqui(re|sition)s?\s+of\s+shares"`).

## Shell completion

```bash
mergers --install-completion   # install for your current shell
mergers --show-completion      # print the completion script
```

Supports bash, zsh, fish and PowerShell via Typer.

## Cache

The first run of any command populates `~/.accc-mergers/db.sqlite`. After 7
days the CLI warns that the cache is stale — run `mergers sync` to refresh.

Sync fetches `cli-manifest.json` from the upstream repo (~270 bytes) and only
downloads the full bundle (`cli-bundle.json`, ~1.6 MB) when its SHA-256 has
changed. A no-op sync is therefore a single HTTP request.

Set `ACCC_MERGERS_BASE_URL` to point at a different source (e.g. a fork or a
local `file://` path) — useful for development against a local checkout of
`accc-mergers/data/output/cli/`.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## License

See [LICENSE](LICENSE).
